"""
Base tool interface.
Every tool defines its name, description, input/output schemas,
and an execute function. Tools are the only way the AI layer
interacts with external providers or performs actions.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator


@dataclass
class ToolInput:
    """Validated input to a tool, carrying the parsed parameters."""

    params: dict[str, Any]


@dataclass
class ToolOutput:
    """Structured result from a tool execution."""

    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolParameter:
    """Describes one parameter of a tool's input schema."""

    name: str
    type: str  # "string", "number", "boolean"
    description: str
    required: bool = True


class Tool(ABC):
    """Abstract base class for all tools."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier (e.g. 'validate_address')."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what the tool does."""

    @property
    @abstractmethod
    def parameters(self) -> list[ToolParameter]:
        """Input parameter schema for this tool."""

    @abstractmethod
    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        """Run the tool with validated input. Returns structured output."""

    def schema(self) -> dict:
        """Return a JSON-serializable schema for LLM tool selection."""
        return {
            "name": self.name,
            "description": self.description,
            "parameters": [
                {
                    "name": p.name,
                    "type": p.type,
                    "description": p.description,
                    "required": p.required,
                }
                for p in self.parameters
            ],
        }

    def input_schema(self) -> dict[str, Any]:
        """Full JSON Schema (draft 2020-12) for this tool's arguments.

        This single schema is the source of truth for BOTH ``/tools/list``
        discovery and ``validate_input`` below. The default here is derived from
        ``parameters`` — typed properties, a ``required`` list, and
        ``additionalProperties: False`` so unexpected fields are rejected.
        Concrete tools override this to add real constraints (patterns, numeric
        ranges, enums); see ``ValidateAddressTool`` / ``GetQuotePreviewTool``.
        """
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in self.parameters:
            properties[p.name] = {"type": p.type, "description": p.description}
            if p.required:
                required.append(p.name)
        return {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        }

    def validate_input(self, params: dict[str, Any]) -> list[str]:
        """Validate ``params`` against ``input_schema()`` using JSON Schema.

        Returns a list of human-readable error messages (empty list = valid).
        The HTTP layer calls this BEFORE ``execute()`` and, on any error,
        returns ``success=false`` with the joined messages — so malformed input
        never reaches a provider. The ``list[str]`` return type is unchanged
        from the original presence-only implementation, so callers are
        unaffected.
        """
        validator = Draft202012Validator(self.input_schema())
        messages: list[str] = []
        for err in sorted(validator.iter_errors(params), key=lambda e: list(e.path)):
            location = ".".join(str(p) for p in err.path)
            messages.append(f"{location}: {err.message}" if location else err.message)
        return messages

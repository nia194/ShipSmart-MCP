"""Tool descriptor integrity (Governance & Guardrails §5.5).

A schema-validated tool is not enough: the descriptor itself (name + description +
input schema) is what an LLM plans against, so a malicious or accidental change to
it is a supply-chain risk. Each descriptor gets a content checksum; pinning the
expected checksums lets the server detect drift (a changed, added, or removed
tool) before serving. Deterministic + keyless.
"""

from __future__ import annotations

import json
from hashlib import sha256

from app.tools.base import Tool
from app.tools.registry import ToolRegistry


def descriptor_checksum(tool: Tool) -> str:
    """Stable sha256 over a tool's descriptor (name + description + input schema)."""
    payload = {
        "name": tool.name,
        "description": tool.description,
        "input_schema": tool.input_schema(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(canonical.encode()).hexdigest()


def registry_checksums(registry: ToolRegistry) -> dict[str, str]:
    """Current descriptor checksum for every registered tool, keyed by name."""
    return {t.name: descriptor_checksum(t) for t in registry.list_tools()}


def verify_descriptors(registry: ToolRegistry, expected: dict[str, str]) -> list[str]:
    """Return a list of drift findings vs the pinned ``expected`` checksums.

    Empty list = descriptors are intact. Findings cover changed, missing, and
    unexpected (newly-appeared) tools.
    """
    current = registry_checksums(registry)
    findings: list[str] = []
    for name, chk in expected.items():
        if name not in current:
            findings.append(f"missing tool: {name}")
        elif current[name] != chk:
            findings.append(f"descriptor changed: {name}")
    for name in current:
        if name not in expected:
            findings.append(f"unexpected tool: {name}")
    return findings

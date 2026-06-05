"""
Quote preview tool.
Returns non-binding shipping rate previews through the provider abstraction.
Does NOT replace Spring Boot quote ownership — this is an AI-assist preview only.
"""

from __future__ import annotations

import logging
from typing import Any

from app.providers.shipping_provider import QuotePreviewInput, ShippingProvider
from app.tools.base import Tool, ToolInput, ToolOutput, ToolParameter

logger = logging.getLogger(__name__)


class GetQuotePreviewTool(Tool):
    """Get a non-binding shipping quote preview."""

    def __init__(self, provider: ShippingProvider) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "get_quote_preview"

    @property
    def description(self) -> str:
        return (
            "Get a non-binding shipping quote preview based on package "
            "dimensions, weight, and origin/destination. "
            "This is an estimate — final quotes come from the Java API."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("origin_zip", "string", "Origin ZIP code"),
            ToolParameter("destination_zip", "string", "Destination ZIP code"),
            ToolParameter("weight_lbs", "number", "Package weight in pounds"),
            ToolParameter("length_in", "number", "Package length in inches"),
            ToolParameter("width_in", "number", "Package width in inches"),
            ToolParameter("height_in", "number", "Package height in inches"),
        ]

    def input_schema(self) -> dict[str, Any]:
        """Strict JSON Schema: US ZIP patterns for origin/destination; weight
        and dimensions must be numbers strictly greater than 0 with sane
        carrier maxima. Non-numeric, zero/negative, out-of-range, or unexpected
        fields are rejected before execution."""
        zip_pattern = r"^\d{5}(-\d{4})?$"
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "origin_zip", "destination_zip",
                "weight_lbs", "length_in", "width_in", "height_in",
            ],
            "properties": {
                "origin_zip": {
                    "type": "string",
                    "pattern": zip_pattern,
                    "description": "Origin ZIP code (5-digit or ZIP+4)",
                },
                "destination_zip": {
                    "type": "string",
                    "pattern": zip_pattern,
                    "description": "Destination ZIP code (5-digit or ZIP+4)",
                },
                "weight_lbs": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 150,
                    "description": "Package weight in pounds (>0, <=150)",
                },
                "length_in": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 108,
                    "description": "Package length in inches (>0, <=108)",
                },
                "width_in": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 108,
                    "description": "Package width in inches (>0, <=108)",
                },
                "height_in": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": 108,
                    "description": "Package height in inches (>0, <=108)",
                },
            },
        }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        try:
            shipment = QuotePreviewInput(
                origin_zip=str(params["origin_zip"]),
                destination_zip=str(params["destination_zip"]),
                weight_lbs=float(params["weight_lbs"]),
                length_in=float(params["length_in"]),
                width_in=float(params["width_in"]),
                height_in=float(params["height_in"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            return ToolOutput(
                success=False,
                error=f"Invalid input: {exc}",
                metadata={"tool": self.name},
            )

        logger.info("Getting quote preview via provider=%s", self._provider.name)
        result = await self._provider.get_quote_preview(shipment)

        return ToolOutput(
            success=result.success,
            data=result.data,
            error=result.error,
            metadata={"provider": result.provider, "tool": self.name},
        )

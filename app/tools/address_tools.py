"""
Address validation tool.
Validates and normalizes shipping addresses through the provider abstraction.
"""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.providers.shipping_provider import AddressInput, ShippingProvider
from app.tools.base import Tool, ToolInput, ToolOutput, ToolParameter

logger = logging.getLogger(__name__)


class ValidateAddressTool(Tool):
    """Validate and normalize a shipping address."""

    def __init__(self, provider: ShippingProvider) -> None:
        self._provider = provider

    @property
    def name(self) -> str:
        return "validate_address"

    @property
    def description(self) -> str:
        return (
            "Validate a shipping address and return a normalized version. "
            "Checks for required fields and format issues."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("street", "string", "Street address line"),
            ToolParameter("city", "string", "City name"),
            ToolParameter("state", "string", "State code (e.g. CA, NY)"),
            ToolParameter("zip_code", "string", "ZIP code (e.g. 90210)"),
            ToolParameter(
                "country", "string", "Country code (default US)",
                required=False,
            ),
        ]

    def input_schema(self) -> dict[str, Any]:
        """Strict JSON Schema: non-empty street/city, 2-letter state code, US
        ZIP (5 or ZIP+4), and an optional country enum that defaults to US.
        Unexpected fields are rejected (additionalProperties: false)."""
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["street", "city", "state", "zip_code"],
            "properties": {
                "street": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Street address line",
                },
                "city": {
                    "type": "string",
                    "minLength": 1,
                    "description": "City name",
                },
                "state": {
                    "type": "string",
                    "pattern": "^[A-Za-z]{2}$",
                    "description": "2-letter state code (e.g. CA, NY)",
                },
                "zip_code": {
                    "type": "string",
                    "pattern": r"^\d{5}(-\d{4})?$",
                    "description": "US ZIP code: 5-digit or ZIP+4 (e.g. 90210 or 90210-1234)",
                },
                "country": {
                    "type": "string",
                    "enum": ["US", "CA", "MX"],
                    "default": "US",
                    "description": "ISO country code (default US)",
                },
            },
        }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        params = tool_input.params
        country = params.get("country", "US")

        # Domestic-only deployments serve the home country only (no-op when worldwide).
        if settings.is_domestic_scope and (country or "").strip().upper() != settings.home_country:
            return ToolOutput(
                success=False,
                error=(
                    f"This deployment serves {settings.home_country} only; "
                    f"country {country} is not supported."
                ),
                metadata={"tool": self.name},
            )

        address = AddressInput(
            street=params.get("street", ""),
            city=params.get("city", ""),
            state=params.get("state", ""),
            zip_code=params.get("zip_code", ""),
            country=country,
        )

        logger.info("Validating address via provider=%s", self._provider.name)
        result = await self._provider.validate_address(address)

        return ToolOutput(
            success=result.success,
            data=result.data,
            error=result.error,
            metadata={"provider": result.provider, "tool": self.name},
        )

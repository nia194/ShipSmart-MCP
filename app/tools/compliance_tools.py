"""Restricted-item check (Product Roadmap §11 backlog — P4).

A read-only, deterministic tool that classifies an item/category as allowed,
warning (ships with rules), or prohibited, WITH a source family — pairing with
the compliance corpus in ShipSmart-API. It advises; it never asserts a shipment
is "cleared" (that stays the deterministic compliance checker's + Java's job, and
the model may only direct attention — see §5.6 / the advisory-only invariant).
"""

from __future__ import annotations

from typing import Any

from app.tools.base import Tool, ToolInput, ToolOutput, ToolParameter

# keyword -> (status, reason, source_family). Ordered most-specific first.
_RESTRICTED_RULES: list[tuple[tuple[str, ...], str, str, str]] = [
    (("lithium", "battery", "batteries", "power bank", "powerbank"),
     "warning", "Lithium batteries are dangerous goods with packaging/labeling rules.",
     "compliance/lithium-batteries-dangerous-goods.md"),
    (("firearm", "gun", "ammunition", "ammo", "explosive", "fireworks"),
     "prohibited", "Weapons/explosives are prohibited or heavily restricted.",
     "compliance/prohibited-restricted-items.md"),
    (("perishable", "food", "fresh", "frozen", "meat", "produce"),
     "warning", "Perishables have customs + handling restrictions and time limits.",
     "compliance/perishable-goods.md"),
    (("alcohol", "wine", "liquor", "spirits", "beer"),
     "warning", "Alcohol requires a licensed shipper and destination restrictions apply.",
     "compliance/alcohol-shipping.md"),
    (("aerosol", "flammable", "paint", "solvent", "hazmat", "hazardous"),
     "warning", "Flammable/hazardous materials are regulated dangerous goods.",
     "compliance/hazardous-materials.md"),
    (("cash", "currency", "counterfeit", "ivory", "drug", "narcotic"),
     "prohibited", "Currency/illicit/protected items are prohibited.",
     "compliance/prohibited-restricted-items.md"),
]


class CheckRestrictedItemsTool(Tool):
    """Item/category → {status: allowed|warning|prohibited, reason, source}."""

    @property
    def name(self) -> str:
        return "check_restricted_items"

    @property
    def description(self) -> str:
        return (
            "Check whether an item or category is allowed, restricted (ships with "
            "rules), or prohibited, with a source. Advisory only; never clears a shipment."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [ToolParameter("item", "string", "Item name or category to check")]

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"item": {"type": "string", "minLength": 1, "maxLength": 200}},
            "required": ["item"],
            "additionalProperties": False,
        }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        item = str(tool_input.params["item"]).strip().lower()
        for keywords, status, reason, source in _RESTRICTED_RULES:
            if any(kw in item for kw in keywords):
                return ToolOutput(
                    success=True,
                    data={"item": item, "status": status, "reason": reason, "source": source},
                    metadata={"advisory_only": True},
                )
        return ToolOutput(
            success=True,
            data={
                "item": item,
                "status": "allowed",
                "reason": "No restriction matched in the known rules; verify for your route.",
                "source": "compliance/prohibited-restricted-items.md",
            },
            metadata={"advisory_only": True},
        )

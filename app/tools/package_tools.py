"""Package-intelligence tools (Product Roadmap §11 backlog — P2/P4).

Two read-only, deterministic tools the assistant uses to help a user describe a
shipment without exact measurements:

* ``calculate_dimensional_weight`` — the carrier billable-weight formula
  (max of actual weight and volumetric weight L*W*H / divisor). Pure arithmetic.
* ``estimate_package_profile`` — a labelled profile (documents / small_box / …)
  to estimated dimensions + weight, clearly flagged ``is_estimate`` so the UI
  badges it and the booking gate still requires exact details (§10).

Both own no state, call no provider, and never invent a price — estimation is a
convenience, the quote is still Java's.
"""

from __future__ import annotations

import math
from typing import Any

from app.tools.base import Tool, ToolInput, ToolOutput, ToolParameter

# Standard domestic dimensional divisor (cubic inches per pound).
DEFAULT_DIM_DIVISOR = 139

# Labelled package profiles → estimated dimensions (in) + weight (lb). Estimates
# only; the booking gate requires exact details.
PACKAGE_PROFILES: dict[str, dict[str, float]] = {
    "documents": {"length_in": 12.0, "width_in": 9.0, "height_in": 1.0, "weight_lbs": 0.5},
    "small_box": {"length_in": 10.0, "width_in": 8.0, "height_in": 6.0, "weight_lbs": 3.0},
    "medium_box": {"length_in": 16.0, "width_in": 12.0, "height_in": 8.0, "weight_lbs": 12.0},
    "large_box": {"length_in": 20.0, "width_in": 16.0, "height_in": 14.0, "weight_lbs": 25.0},
    "suitcase": {"length_in": 27.0, "width_in": 18.0, "height_in": 11.0, "weight_lbs": 30.0},
    "electronics": {"length_in": 14.0, "width_in": 10.0, "height_in": 6.0, "weight_lbs": 8.0},
}


class CalculateDimensionalWeightTool(Tool):
    """Billable weight = max(actual, volumetric); volumetric = L*W*H / divisor."""

    @property
    def name(self) -> str:
        return "calculate_dimensional_weight"

    @property
    def description(self) -> str:
        return (
            "Compute a package's dimensional (volumetric) weight and the billable "
            "weight a carrier charges: max of actual and dimensional weight."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter("length_in", "number", "Length in inches"),
            ToolParameter("width_in", "number", "Width in inches"),
            ToolParameter("height_in", "number", "Height in inches"),
            ToolParameter("actual_weight_lbs", "number", "Actual weight in pounds"),
            ToolParameter("divisor", "number", "Dimensional divisor (default 139)", required=False),
        ]

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "length_in": {"type": "number", "exclusiveMinimum": 0},
                "width_in": {"type": "number", "exclusiveMinimum": 0},
                "height_in": {"type": "number", "exclusiveMinimum": 0},
                "actual_weight_lbs": {"type": "number", "minimum": 0},
                "divisor": {"type": "number", "exclusiveMinimum": 0},
            },
            "required": ["length_in", "width_in", "height_in", "actual_weight_lbs"],
            "additionalProperties": False,
        }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        p = tool_input.params
        divisor = float(p.get("divisor") or DEFAULT_DIM_DIVISOR)
        volume = float(p["length_in"]) * float(p["width_in"]) * float(p["height_in"])
        dim_weight = math.ceil(volume / divisor)
        actual = float(p["actual_weight_lbs"])
        billable = max(actual, float(dim_weight))
        return ToolOutput(
            success=True,
            data={
                "dimensional_weight_lbs": dim_weight,
                "actual_weight_lbs": actual,
                "billable_weight_lbs": billable,
                "basis": "dimensional" if dim_weight > actual else "actual",
                "divisor": divisor,
            },
        )


class EstimatePackageProfileTool(Tool):
    """Map a labelled profile to estimated dims + weight (flagged as estimates)."""

    @property
    def name(self) -> str:
        return "estimate_package_profile"

    @property
    def description(self) -> str:
        return (
            "Estimate dimensions and weight from a package profile "
            f"({', '.join(sorted(PACKAGE_PROFILES))}). Estimates only; booking needs exact details."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [ToolParameter("profile", "string", "One of the known package profiles")]

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"profile": {"type": "string", "enum": sorted(PACKAGE_PROFILES)}},
            "required": ["profile"],
            "additionalProperties": False,
        }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        profile = str(tool_input.params["profile"]).strip().lower()
        dims = PACKAGE_PROFILES.get(profile)
        if dims is None:
            return ToolOutput(
                success=False,
                error=f"unknown profile {profile!r}; known: {sorted(PACKAGE_PROFILES)}",
            )
        return ToolOutput(
            success=True,
            data={"profile": profile, "is_estimate": True, **dims},
            metadata={"note": "estimated dimensions; exact details required before booking"},
        )

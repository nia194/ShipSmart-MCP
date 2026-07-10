"""Package-intelligence tool tests (Product Roadmap §11 — P2/P4)."""

from __future__ import annotations

import pytest

from app.tools.base import ToolInput
from app.tools.package_tools import (
    CalculateDimensionalWeightTool,
    EstimatePackageProfileTool,
)

dim_tool = CalculateDimensionalWeightTool()
profile_tool = EstimatePackageProfileTool()


# ── dimensional weight ────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_dimensional_weight_billable_is_the_larger():
    # 20x16x14 = 4480 in^3 / 139 = 32.2 -> ceil 33 lb dim; actual 10 -> billable 33.
    out = await dim_tool.execute(
        ToolInput({"length_in": 20, "width_in": 16, "height_in": 14, "actual_weight_lbs": 10})
    )
    assert out.success
    assert out.data["dimensional_weight_lbs"] == 33
    assert out.data["billable_weight_lbs"] == 33 and out.data["basis"] == "dimensional"


@pytest.mark.asyncio
async def test_actual_weight_wins_for_dense_packages():
    out = await dim_tool.execute(
        ToolInput({"length_in": 6, "width_in": 6, "height_in": 6, "actual_weight_lbs": 40})
    )
    assert out.data["billable_weight_lbs"] == 40 and out.data["basis"] == "actual"


def test_dimensional_weight_rejects_nonpositive_dims():
    errs = dim_tool.validate_input(
        {"length_in": 0, "width_in": 6, "height_in": 6, "actual_weight_lbs": 1}
    )
    assert errs  # exclusiveMinimum 0 violated


# ── package profile ───────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_profile_returns_estimated_dims_flagged():
    out = await profile_tool.execute(ToolInput({"profile": "medium_box"}))
    assert out.success and out.data["is_estimate"] is True
    assert out.data["length_in"] == 16.0 and out.data["weight_lbs"] == 12.0
    assert "exact details" in out.metadata["note"]


@pytest.mark.asyncio
async def test_unknown_profile_fails_cleanly():
    out = await profile_tool.execute(ToolInput({"profile": "spaceship"}))
    assert not out.success and "unknown profile" in out.error


def test_profile_schema_is_enum_constrained():
    assert profile_tool.validate_input({"profile": "not_a_profile"})  # enum violation
    assert not profile_tool.validate_input({"profile": "documents"})


def test_both_tools_declare_read_only_names():
    assert dim_tool.name == "calculate_dimensional_weight"
    assert profile_tool.name == "estimate_package_profile"

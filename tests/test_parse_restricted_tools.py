"""parse_address + check_restricted_items tool tests (roadmap §11 — P2/P4)."""

from __future__ import annotations

import pytest

from app.tools.base import ToolInput
from app.tools.compliance_tools import CheckRestrictedItemsTool
from app.tools.parse_tools import ParseAddressTool

parse = ParseAddressTool()
restricted = CheckRestrictedItemsTool()


# ── parse_address ─────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_full_address_parses_with_high_confidence():
    out = await parse.execute(ToolInput({"address": "123 Main St, Springfield, IL 62704"}))
    c = out.data["components"]
    assert c["state"] == "IL" and c["postal_code"] == "62704" and c["country"] == "US"
    assert c["street"] == "123 Main St"
    assert out.data["is_complete"] is False or out.data["confidence"] >= 0.8


@pytest.mark.asyncio
async def test_partial_address_reports_missing_not_guessed():
    out = await parse.execute(ToolInput({"address": "somewhere downtown"}))
    assert out.data["confidence"] < 0.6
    assert "state" in out.data["missing"] and out.data["components"]["state"] is None


def test_parse_rejects_empty():
    assert parse.validate_input({"address": ""})  # minLength 1 violated


# ── check_restricted_items ────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_lithium_is_a_warning_with_source():
    out = await restricted.execute(ToolInput({"item": "a spare lithium battery"}))
    assert out.data["status"] == "warning" and out.data["source"].startswith("compliance/")
    assert out.metadata["advisory_only"] is True


@pytest.mark.asyncio
async def test_firearm_is_prohibited():
    out = await restricted.execute(ToolInput({"item": "handgun ammunition"}))
    assert out.data["status"] == "prohibited"


@pytest.mark.asyncio
async def test_ordinary_item_is_allowed_but_never_cleared_language():
    out = await restricted.execute(ToolInput({"item": "cotton t-shirt"}))
    assert out.data["status"] == "allowed"
    # advisory only — never the word "cleared"
    assert "cleared" not in out.data["reason"].lower()


def test_tool_names():
    assert parse.name == "parse_address" and restricted.name == "check_restricted_items"

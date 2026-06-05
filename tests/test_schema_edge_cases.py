"""Schema boundary / corner-case tests for the MCP tool validation."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as mcp_main

_ADDR = {"street": "1 Main St", "city": "Los Angeles", "state": "CA", "zip_code": "90001"}
_QUOTE = {
    "origin_zip": "90210", "destination_zip": "10001",
    "weight_lbs": 5, "length_in": 12, "width_in": 8, "height_in": 6,
}


@pytest.fixture
def client():
    return TestClient(mcp_main.app)


def _call(client, name, args):
    return client.post("/tools/call", json={"name": name, "arguments": args}).json()


# ── accepted boundaries ──────────────────────────────────────────────────────


@pytest.mark.parametrize("args", [
    {**_ADDR, "zip_code": "90210-1234"},   # ZIP+4
    {**_ADDR, "state": "ca"},              # lowercase (provider upper-cases)
    {**_ADDR, "country": "CA"},            # enum member
    {**_ADDR, "country": "MX"},
])
def test_validate_address_accepts_valid_boundaries(client, args):
    assert _call(client, "validate_address", args)["success"] is True


@pytest.mark.parametrize("args", [
    {**_QUOTE, "weight_lbs": 150},                                   # max weight (inclusive)
    {**_QUOTE, "length_in": 108, "width_in": 108, "height_in": 108}, # max dims (inclusive)
    {**_QUOTE, "weight_lbs": 0.1},                                   # just above 0
    {**_QUOTE, "origin_zip": "90210-1234"},                         # ZIP+4
    {**_QUOTE, "weight_lbs": 5.0},                                   # float
])
def test_quote_preview_accepts_valid_boundaries(client, args):
    assert _call(client, "get_quote_preview", args)["success"] is True


# ── rejected boundaries (pre-execution, success=false) ───────────────────────


@pytest.mark.parametrize("args,needle", [
    ({**_ADDR, "zip_code": "9021"}, "zip_code"),        # too short
    ({**_ADDR, "zip_code": "902100"}, "zip_code"),      # too long
    ({**_ADDR, "state": "California"}, "state"),        # not 2 letters
    ({**_ADDR, "state": "C"}, "state"),                 # 1 letter
    ({**_ADDR, "country": "ZZ"}, "country"),            # not in enum
    ({**_ADDR, "street": "   "}, None),                 # whitespace street → provider/empty
])
def test_validate_address_rejects_bad_boundaries(client, args, needle):
    body = _call(client, "validate_address", args)
    assert body["success"] is False
    if needle:
        assert needle in body["error"]


@pytest.mark.parametrize("args,needle", [
    ({**_QUOTE, "weight_lbs": 0}, "weight_lbs"),        # exclusiveMinimum
    ({**_QUOTE, "weight_lbs": -1}, "weight_lbs"),       # negative
    ({**_QUOTE, "weight_lbs": 150.5}, "weight_lbs"),    # over max
    ({**_QUOTE, "height_in": 109}, "height_in"),        # over max dim
    ({**_QUOTE, "weight_lbs": True}, "weight_lbs"),     # bool is not a number
    ({**_QUOTE, "weight_lbs": "5"}, "weight_lbs"),      # string is not a number
    ({**_QUOTE, "origin_zip": "ABCDE"}, "origin_zip"),  # non-numeric zip
])
def test_quote_preview_rejects_bad_boundaries(client, args, needle):
    body = _call(client, "get_quote_preview", args)
    assert body["success"] is False
    assert needle in body["error"]

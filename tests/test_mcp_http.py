"""End-to-end tests for the MCP HTTP contract (/tools/list, /tools/call, auth)."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

import app.main as mcp_main
from app.core.config import settings
from app.providers.shipping_provider import (
    AddressInput,
    QuotePreviewInput,
    ShippingProvider,
)
from app.tools.address_tools import ValidateAddressTool
from app.tools.base import Tool, ToolInput, ToolOutput
from app.tools.quote_tools import GetQuotePreviewTool
from app.tools.registry import ToolRegistry


@pytest.fixture
def client():
    return TestClient(mcp_main.app)


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "healthy"
    assert body["tools"] >= 2


def test_root_discovery(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert "endpoints" in body
    assert body["tools_count"] >= 2


def test_tools_list(client):
    resp = client.post("/tools/list")
    assert resp.status_code == 200
    body = resp.json()
    tool_names = [t["name"] for t in body["tools"]]
    assert "validate_address" in tool_names
    assert "get_quote_preview" in tool_names
    # Each tool must have a JSON Schema input_schema
    for tool in body["tools"]:
        assert tool["input_schema"]["type"] == "object"
        assert "properties" in tool["input_schema"]


def test_tools_call_validate_address(client):
    resp = client.post("/tools/call", json={
        "name": "validate_address",
        "arguments": {
            "street": "123 Main St",
            "city": "Los Angeles",
            "state": "CA",
            "zip_code": "90001",
        },
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert len(body["content"]) >= 1
    assert body["content"][0]["type"] == "text"


def test_tools_call_quote_preview(client):
    resp = client.post("/tools/call", json={
        "name": "get_quote_preview",
        "arguments": {
            "origin_zip": "90210",
            "destination_zip": "10001",
            "weight_lbs": 5.0,
            "length_in": 12.0,
            "width_in": 8.0,
            "height_in": 6.0,
        },
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True


def test_tools_call_unknown_tool(client):
    resp = client.post("/tools/call", json={
        "name": "not_a_tool",
        "arguments": {},
    })
    assert resp.status_code == 404


def test_tools_call_missing_required_param(client):
    resp = client.post("/tools/call", json={
        "name": "validate_address",
        "arguments": {"street": "only street provided"},
    })
    assert resp.status_code == 200  # validation failure reported in body, not HTTP
    body = resp.json()
    assert body["success"] is False
    assert body["error"]


def test_api_key_required_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "mcp_api_key", "secret-token", raising=False)

    resp = client.post("/tools/list")
    assert resp.status_code == 401

    resp = client.post("/tools/list", headers={"X-MCP-Api-Key": "wrong"})
    assert resp.status_code == 401

    resp = client.post("/tools/list", headers={"X-MCP-Api-Key": "secret-token"})
    assert resp.status_code == 200


def test_api_key_not_enforced_when_empty(client, monkeypatch):
    monkeypatch.setattr(settings, "mcp_api_key", "", raising=False)
    resp = client.post("/tools/list")
    assert resp.status_code == 200


def test_health_and_root_bypass_api_key_gate(client, monkeypatch):
    """The API-key gate guards only /tools/*; the liveness/discovery probes
    (/health, /) must stay reachable WITHOUT the shared secret so a load
    balancer or uptime check can poll them. /tools/* stays gated."""
    monkeypatch.setattr(settings, "mcp_api_key", "secret-token", raising=False)
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    assert client.post("/tools/list").status_code == 401  # tools still gated


def test_validate_address_country_is_optional_and_defaults(client):
    """`country` is optional by contract (absent from `required`) and defaults
    to US in execute(); omitting it must still validate and succeed."""
    schema = {
        t["name"]: t["input_schema"] for t in client.post("/tools/list").json()["tools"]
    }["validate_address"]
    assert "country" not in schema["required"]   # optional…
    assert "country" in schema["properties"]     # …but advertised
    resp = client.post(
        "/tools/call", json={"name": "validate_address", "arguments": _VALID_ADDR}
    )
    assert resp.status_code == 200 and resp.json()["success"] is True


# ── /tools/list now emits a rich JSON Schema ─────────────────────────────────


def test_tools_list_emits_rich_schema(client):
    body = client.post("/tools/list").json()
    schemas = {t["name"]: t["input_schema"] for t in body["tools"]}

    va = schemas["validate_address"]
    assert va["additionalProperties"] is False
    assert set(va["required"]) == {"street", "city", "state", "zip_code"}
    assert va["properties"]["state"]["pattern"]
    assert va["properties"]["zip_code"]["pattern"]
    assert va["properties"]["country"]["enum"]

    gq = schemas["get_quote_preview"]
    assert gq["additionalProperties"] is False
    assert gq["properties"]["weight_lbs"]["type"] == "number"
    assert gq["properties"]["weight_lbs"]["exclusiveMinimum"] == 0
    assert gq["properties"]["origin_zip"]["pattern"]


# ── Malformed input is rejected BEFORE the provider runs ─────────────────────


class _BoomProvider(ShippingProvider):
    """Provider that explodes if any execute path reaches it.

    Proves schema validation rejects malformed input *before* execute(): if a
    provider method is ever called, ``calls`` increments and the test fails.
    """

    def __init__(self) -> None:
        self.calls = 0

    @property
    def name(self) -> str:
        return "boom"

    async def health_check(self) -> bool:
        return True

    async def validate_address(self, address: AddressInput):
        self.calls += 1
        raise AssertionError("provider must not run on invalid input")

    async def get_quote_preview(self, shipment: QuotePreviewInput):
        self.calls += 1
        raise AssertionError("provider must not run on invalid input")


@pytest.fixture
def boom_provider(monkeypatch):
    """Swap the live registry for one whose provider must never be executed."""
    boom = _BoomProvider()
    registry = ToolRegistry()
    registry.register(ValidateAddressTool(boom))
    registry.register(GetQuotePreviewTool(boom))
    monkeypatch.setattr(mcp_main, "_tool_registry", registry)
    return boom


_VALID_ADDR = {
    "street": "123 Main St", "city": "Los Angeles", "state": "CA", "zip_code": "90001",
}
_VALID_QUOTE = {
    "origin_zip": "90210", "destination_zip": "10001",
    "weight_lbs": 5.0, "length_in": 12.0, "width_in": 8.0, "height_in": 6.0,
}


@pytest.mark.parametrize(
    "tool_name,arguments,needle",
    [
        # validate_address: bad state, bad zip, empty street, missing, extra, bad enum
        ("validate_address", {**_VALID_ADDR, "state": "California"}, "state"),
        ("validate_address", {**_VALID_ADDR, "zip_code": "ABCDE"}, "zip_code"),
        ("validate_address", {**_VALID_ADDR, "street": ""}, "street"),
        ("validate_address", {"street": "only street provided"}, "required"),
        ("validate_address", {**_VALID_ADDR, "unexpected": "x"}, "Additional"),
        ("validate_address", {**_VALID_ADDR, "country": "ZZ"}, "country"),
        # get_quote_preview: wrong type, negative, zero, bad zip, missing, extra
        ("get_quote_preview", {**_VALID_QUOTE, "weight_lbs": "heavy"}, "weight_lbs"),
        ("get_quote_preview", {**_VALID_QUOTE, "weight_lbs": -3}, "weight_lbs"),
        ("get_quote_preview", {**_VALID_QUOTE, "height_in": 0}, "height_in"),
        ("get_quote_preview", {**_VALID_QUOTE, "origin_zip": "ABCDE"}, "origin_zip"),
        ("get_quote_preview", {"origin_zip": "90210"}, "required"),
        ("get_quote_preview", {**_VALID_QUOTE, "extra": 1}, "Additional"),
    ],
)
def test_malformed_input_rejected_without_provider(
    client, boom_provider, tool_name, arguments, needle
):
    resp = client.post("/tools/call", json={"name": tool_name, "arguments": arguments})
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["content"] == []          # nothing was executed
    assert needle in body["error"]
    assert boom_provider.calls == 0       # provider was never reached


def test_valid_input_passes_gate_to_execute(client, boom_provider):
    """Valid args clear validation and DO reach execute() — proven by the boom
    provider being invoked exactly once (it then raises, which the handler maps
    to success=false). This confirms the gate lets good input through."""
    resp = client.post(
        "/tools/call", json={"name": "validate_address", "arguments": _VALID_ADDR}
    )
    assert resp.status_code == 200
    assert boom_provider.calls == 1


def test_provider_exception_during_execute_is_mapped_to_failure(client, boom_provider):
    """A provider that raises *after* clearing validation is caught by the
    /tools/call handler and reported as success=false on HTTP 200 — never a 500
    or a leaked stack trace. This locks the handler's execute-time error branch
    so a flaky carrier degrades gracefully for every consumer."""
    resp = client.post(
        "/tools/call", json={"name": "validate_address", "arguments": _VALID_ADDR}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is False
    assert body["content"] == []     # no content emitted on a thrown execute
    assert body["error"]             # the failure reason is surfaced to the caller
    assert boom_provider.calls == 1  # the failure came from execute(), not the gate


def test_valid_call_content_shape_unchanged(client):
    """With the real mock provider, a valid call returns the exact wire shape
    mcp_client.py parses: a JSON data text block + a trailing 'Metadata:' block."""
    resp = client.post(
        "/tools/call", json={"name": "get_quote_preview", "arguments": _VALID_QUOTE}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["error"] is None
    assert body["content"][0]["type"] == "text"
    data = json.loads(body["content"][0]["text"])
    assert isinstance(data.get("services"), list)
    assert any(b["text"].startswith("Metadata:") for b in body["content"][1:])


# ── Read-only / least-privilege invariant ────────────────────────────────────


def test_registry_exposes_only_read_only_tools(client):
    registry = mcp_main.get_tool_registry()
    names = {tool.name for tool in registry.list_tools()}
    assert names                                      # registry is non-empty
    assert names <= mcp_main.READ_ONLY_TOOL_ALLOWLIST


def test_enforce_read_only_rejects_non_preview_tool():
    """The invariant is real: registering a write/booking tool fails fast."""

    class _BookShipmentTool(Tool):
        @property
        def name(self) -> str:
            return "book_shipment"

        @property
        def description(self) -> str:
            return "would create a shipment (a write — forbidden on this server)"

        @property
        def parameters(self):
            return []

        async def execute(self, tool_input: ToolInput) -> ToolOutput:
            return ToolOutput(success=True)

    registry = ToolRegistry()
    registry.register(_BookShipmentTool())
    with pytest.raises(RuntimeError, match="read-only"):
        mcp_main._enforce_read_only(registry)

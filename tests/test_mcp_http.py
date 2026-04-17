"""End-to-end tests for the MCP HTTP contract (/tools/list, /tools/call, auth)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as mcp_main
from app.core.config import settings


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

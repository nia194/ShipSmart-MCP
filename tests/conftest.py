"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

import app.main as mcp_main
from app.core.config import settings


@pytest.fixture(autouse=True)
def _reset_registry_and_auth(monkeypatch):
    """Rebuild the singleton registry for every test and default auth off.

    Tests that want to exercise the API-key gate can override mcp_api_key
    inside the test body.
    """
    monkeypatch.setattr(mcp_main, "_tool_registry", None, raising=False)
    monkeypatch.setattr(settings, "mcp_api_key", "", raising=False)
    monkeypatch.setattr(settings, "shipping_provider", "mock", raising=False)
    yield

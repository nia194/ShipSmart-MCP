"""Tool guard tests (§5.5) — SSRF egress allowlist + per-caller authorization."""

from __future__ import annotations

import pytest

from app.core import tool_guard
from app.core.tool_audit import InMemoryToolAuditSink, record_tool_call

# Derive a real allowed host from config so the tests are env-independent
# (the fedex default is a sandbox host; api.usps.com / onlinetools.ups.com are stable).
_ALLOWED_HOST = next(iter(tool_guard.allowed_hosts()))


# ── egress allowlist (SSRF defense) ───────────────────────────────────────────
def test_allowlisted_carrier_host_passes():
    assert tool_guard.check_egress(f"https://{_ALLOWED_HOST}/track/v1")


def test_arbitrary_host_is_denied():
    assert not tool_guard.check_egress("https://evil.example.com/steal")
    assert not tool_guard.check_egress("http://attacker.internal/x")


def test_link_local_metadata_address_is_denied():
    # The classic cloud SSRF target must never be reachable.
    assert not tool_guard.check_egress("http://169.254.169.254/latest/meta-data/")
    assert not tool_guard.check_egress("http://127.0.0.1:8080/admin")
    assert not tool_guard.check_egress("http://10.0.0.5/internal")


def test_assert_egress_raises_on_denied():
    tool_guard.assert_egress_allowed(f"https://{_ALLOWED_HOST}/x")  # ok, no raise
    with pytest.raises(tool_guard.EgressDeniedError):
        tool_guard.assert_egress_allowed("https://169.254.169.254/")


def test_allowed_hosts_derived_from_config():
    hosts = tool_guard.allowed_hosts()
    # USPS + UPS defaults are stable production hosts (not sandbox-swapped).
    assert "api.usps.com" in hosts and "onlinetools.ups.com" in hosts


# ── per-caller authorization ──────────────────────────────────────────────────
def test_known_caller_and_tool_is_authorized():
    assert tool_guard.is_authorized("shipsmart-api", "get_quote_preview")
    assert tool_guard.is_authorized("shipsmart-api", "validate_address")


def test_unknown_caller_is_denied():
    assert not tool_guard.is_authorized("stranger", "get_quote_preview")


def test_known_caller_off_scope_tool_is_denied():
    assert not tool_guard.is_authorized("shipsmart-api", "create_booking")
    with pytest.raises(tool_guard.CallerDeniedError):
        tool_guard.assert_authorized("shipsmart-api", "create_booking")


# ── a denial is auditable with an error class ─────────────────────────────────
def test_denial_is_auditable_with_error_class():
    sink = InMemoryToolAuditSink()
    try:
        tool_guard.assert_authorized("stranger", "get_quote_preview")
    except tool_guard.CallerDeniedError as e:
        record_tool_call(
            sink, tool="get_quote_preview", caller="stranger", status="denied",
            error_class=type(e).__name__,
        )
    rec = sink.records[0]
    assert rec.status == "denied" and rec.error_class == "CallerDeniedError"

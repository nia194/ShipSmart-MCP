"""Tool guard (Governance & Guardrails §5.5) — egress allowlist + per-caller auth.

Schemas alone are not MCP security. Two request-time checks that fail closed
before any tool executes:

* **Network egress allowlist (SSRF defense).** A tool argument that resolves to a
  URL/host may only reach a configured carrier host — never an arbitrary URL,
  never a link-local/metadata address. Anything else is denied before the call.
* **Per-caller authorization.** Each caller identity has a scope of tools it may
  invoke; an unknown caller or an off-scope tool is denied — not merely "presented
  the shared API key". Today MCP serves one trusted caller (ShipSmart-API); the
  scope map is the seam a multi-caller / B2B future extends.

Both denials are auditable — the caller and a ``denied`` status with an error
class land in the tool audit (``app/core/tool_audit.py``).
"""

from __future__ import annotations

from ipaddress import ip_address
from urllib.parse import urlparse

from app.core.config import settings


class EgressDeniedError(ValueError):
    """A tool tried to reach a host outside the carrier allowlist (SSRF defense)."""


class CallerDeniedError(ValueError):
    """A caller invoked a tool outside its authorized scope."""


def allowed_hosts() -> set[str]:
    """Carrier hosts a tool may reach, derived from the configured base URLs."""
    hosts: set[str] = set()
    for url in (
        settings.ups_base_url,
        settings.fedex_base_url,
        settings.dhl_base_url,
        settings.usps_base_url,
    ):
        host = urlparse(url).hostname
        if host:
            hosts.add(host.lower())
    return hosts


def _is_public(host: str) -> bool:
    """False for link-local/loopback/private literals (metadata SSRF targets)."""
    try:
        return not ip_address(host).is_private
    except ValueError:
        return True  # a hostname, not an IP literal — allowlist decides


def check_egress(url: str) -> bool:
    """True only if ``url`` targets an allowlisted, non-private carrier host."""
    host = (urlparse(url).hostname or "").lower()
    if not host or not _is_public(host):
        return False
    return host in allowed_hosts()


def assert_egress_allowed(url: str) -> None:
    if not check_egress(url):
        raise EgressDeniedError(f"egress to {url!r} denied — not an allowlisted carrier host")


# Per-caller tool scope. Mirrors READ_ONLY_TOOL_ALLOWLIST (main.py); the API↔MCP
# tool-name agreement is asserted by ShipSmart-Test's tool-policy contract.
DEFAULT_CALLER_SCOPES: dict[str, frozenset[str]] = {
    "shipsmart-api": frozenset({"validate_address", "get_quote_preview"}),
}


def is_authorized(
    caller: str, tool: str, scopes: dict[str, frozenset[str]] | None = None
) -> bool:
    allowed = (scopes or DEFAULT_CALLER_SCOPES).get(caller)
    return bool(allowed and tool in allowed)


def assert_authorized(
    caller: str, tool: str, scopes: dict[str, frozenset[str]] | None = None
) -> None:
    if not is_authorized(caller, tool, scopes):
        raise CallerDeniedError(f"caller {caller!r} not authorized for tool {tool!r}")

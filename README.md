# ShipSmart — MCP Tool Server (`mcp`)

[![FastAPI](https://img.shields.io/badge/FastAPI-0.135.3-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![uv](https://img.shields.io/badge/uv-0.6%2B-DE5FE9?logo=python&logoColor=white)](https://docs.astral.sh/uv/)
[![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-tools%2Flist%20%2B%20tools%2Fcall-7B61FF)](https://modelcontextprotocol.io/)
[![Read-only](https://img.shields.io/badge/tools-read--only%20by%20boot%20invariant-FF8A5B)](#the-headline-invariant)
[![Tests](https://img.shields.io/badge/tests-94%20keyless-3FB950?logo=pytest&logoColor=white)](#tests)
[![Live](https://img.shields.io/badge/Live-%2Fhealth-46E3B7?logo=render&logoColor=white)](https://shipsmart-mcp.onrender.com/health)
[![License](https://img.shields.io/badge/License-See%20LICENSE-blue)](./LICENSE)

> The platform's **sandboxed tool boundary**: a standalone **Model Context
> Protocol** server exposing a *least-privilege, read-only, JSON-Schema-
> validated* tool registry. It is the only component that touches external
> carrier APIs — and by construction the place that can never write, book, or
> move money: **register a write tool and the service refuses to boot.**

Single source of truth for tool behavior across the platform:
[`ShipSmart-API`](https://github.com/nia194/ShipSmart-API) calls this server
over MCP/HTTP instead of implementing tools in-process.

**Stack:** FastAPI 0.135.3 · Python 3.13 (async) · uv · pydantic-settings ·
httpx · JSON Schema Draft 2020-12 · FedEx / UPS / USPS / DHL adapters (+ mock)

**Live:** [`GET /health`](https://shipsmart-mcp.onrender.com/health) (service +
registered tool count) · [`GET /`](https://shipsmart-mcp.onrender.com/)
discovery *(Render free tier — cold start ~30–60 s).*

---

## Table of contents

- [The ShipSmart ecosystem](#the-shipsmart-ecosystem)
- [The headline invariant](#the-headline-invariant)
- [HTTP contract](#http-contract)
- [Tools](#tools)
- [Security layers](#security-layers)
- [Architecture](#architecture)
- [Running locally](#running-locally)
- [Configuration](#configuration)
- [Tests](#tests)
- [License](#license)

---

## The ShipSmart ecosystem

One of six sibling repositories — clone them as siblings of this directory.
All six are also mirrored together in
**[ShipSmart](https://github.com/nia194/ShipSmart)** — the umbrella repository
that snapshots each component at a pinned commit (see its `COMPONENTS.yml`).

| Repo | Role | Stack |
|------|------|-------|
| [ShipSmart-Web](https://github.com/nia194/ShipSmart-Web) | React SPA — search-first UI | React 19, Vite, TS |
| [ShipSmart-Orchestrator](https://github.com/nia194/ShipSmart-Orchestrator) | Java system of record — single Postgres writer, AI trust boundary | Spring Boot 3.4, Java 17 |
| [ShipSmart-API](https://github.com/nia194/ShipSmart-API) | Python AI layer — RAG, guardrails, agents, streaming | FastAPI, Python 3.13 |
| **[ShipSmart-MCP](https://github.com/nia194/ShipSmart-MCP)** *(this repo)* | Read-only MCP tool server — 6 tools, 4+1 carrier adapters | FastAPI + MCP |
| [ShipSmart-Infra](https://github.com/nia194/ShipSmart-Infra) | Supabase schema, RLS, WORM ledger, edge functions | Supabase, Deno |
| [ShipSmart-Test](https://github.com/nia194/ShipSmart-Test) | Cross-repo contracts + evals + e2e | Python 3.13, pytest |

---

## The headline invariant

`READ_ONLY_TOOL_ALLOWLIST` is a **`frozenset`**, and `_enforce_read_only()` runs
at startup:

```
Refusing to start: non-read-only tool(s) registered: [...].
ShipSmart-MCP serves read/preview tools only; writes, bookings, and
money movement belong to the Java Orchestrator.
```

Least privilege as a **boot-time property**, not a runtime hope: a developer who
registers a write tool can't even start the service — the mistake fails loudly
in dev and CI, never silently in production.

## HTTP contract

| Endpoint | Purpose |
|---|---|
| `GET /` | discovery/info |
| `GET /health` | service + registered tool count |
| `POST /tools/list` | MCP discovery — full JSON Schemas per tool |
| `POST /tools/call` | execute one tool (auth + validation + guard + audit) |

`X-MCP-Api-Key` (shared key) gates the tool routes — this is an internal
service, called by the API, never by browsers.

## Tools

| Tool | Kind | Honest semantics |
|---|---|---|
| `validate_address` | carrier-backed | deliverability / normalization |
| `get_quote_preview` | carrier-backed | **preview** pricing — never bookable |
| `calculate_dimensional_weight` | pure | billable = max(actual, L·W·H ÷ divisor) |
| `estimate_package_profile` | pure | labelled profile → estimated dims, `is_estimate` flagged |
| `parse_address` | pure | freeform → components + rule-derived confidence; **reports missing parts, never guesses** |
| `check_restricted_items` | corpus-backed | allowed/warning/prohibited + source; **advisory-only — never asserts "cleared"** |

Every tool subclasses one `Tool` ABC that derives a full **JSON Schema (Draft
2020-12)** — typed properties, `required`, **`additionalProperties: false`** —
and runs `validate_input()` **before** `execute()`. One schema powers both
discovery and enforcement.

## Security layers

Five independent controls stack on every call:

1. **Shared-key auth** (`require_api_key`).
2. **SSRF egress allowlist** (`app/core/tool_guard.py`) — tools may only reach
   allowlisted carrier hosts; private/loopback/link-local IP literals (cloud
   metadata endpoints) are denied **before any network I/O**.
3. **Per-caller tool scopes** — an unknown caller or off-scope tool is denied,
   not merely hidden.
4. **Descriptor integrity** (`app/tools/integrity.py`) — sha256 checksums over
   each tool's name + description + schema; drift (changed/added/removed
   descriptors) is detectable. The tool list the model sees is itself a
   supply-chain surface.
5. **Append-only tool audit** (`app/core/tool_audit.py`) — tool, version,
   caller, request_id, **args-hash** (never raw args — PII-safe), status,
   error_class, latency_ms.

## Architecture

```
  ShipSmart-API ──(MCP/HTTP + X-MCP-Api-Key)──▶ FastAPI app
      └─▶ ToolRegistry (6 tools, self-describing schemas)
             ├─ JSON-Schema validate → tool_guard (egress + scopes) → execute
             ├─ integrity: descriptor checksums
             └─ tool_audit: append-only, args-hashed
      └─▶ ShippingProvider port → FedEx | UPS | USPS | DHL | Mock (default)
            (httpx, explicit timeouts, sandbox base URLs)
```

Adding a carrier is a new adapter — the tools never change. `_build_registry()`
is module-level so tests can rebuild the registry after monkey-patching.

## Running locally

```bash
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
curl localhost:8001/health        # {"service":"shipsmart-mcp","tools":N}
```

Keyless by default (`SHIPPING_PROVIDER=mock`). Set carrier credentials via env
to hit sandboxes.

## Configuration

| Env | Effect |
|---|---|
| `MCP_API_KEY` | shared key for `/tools/*` (empty ⇒ open, dev only) |
| `SHIPPING_PROVIDER` | `mock` (default) · `fedex` · `ups` · `usps` · `dhl` |
| carrier `*_CLIENT_ID` / `*_SECRET` / base URLs | sandbox-by-default adapters |

## Tests

```bash
uv run pytest        # 94 tests — keyless (mock provider), fast
uv run ruff check .
```

The API↔MCP tool-policy contract is additionally asserted by
**ShipSmart-Test** in CI.

## License

See [LICENSE](./LICENSE).

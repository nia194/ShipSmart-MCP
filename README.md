# ShipSmart — MCP Tool Server (`mcp`)

[![FastAPI](https://img.shields.io/badge/FastAPI-0.135.3-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![uv](https://img.shields.io/badge/uv-0.6%2B-DE5FE9?logo=python&logoColor=white)](https://docs.astral.sh/uv/)
[![MCP](https://img.shields.io/badge/Model%20Context%20Protocol-tools%2Flist%20%2B%20tools%2Fcall-7B61FF)](https://modelcontextprotocol.io/)
[![Deploy: Render](https://img.shields.io/badge/Deploy-Render-46E3B7?logo=render&logoColor=white)](https://render.com/)
[![License](https://img.shields.io/badge/License-See%20LICENSE-blue)](./LICENSE)

Standalone **MCP (Model Context Protocol) server** exposing ShipSmart's
shipping tools (`validate_address`, `get_quote_preview`, …) over a small
HTTP contract.

It is the single source of truth for tool behavior across the platform.
Both [`ShipSmart-API`](https://github.com/nia194/ShipSmart-API) (Python /
FastAPI — RAG & advisors) and
[`ShipSmart-Orchestrator`](https://github.com/nia194/ShipSmart-Orchestrator)
(Java / Spring Boot — upcoming AI features) call this server instead of
implementing tools in-process.

**Stack:** FastAPI 0.135.3 · Python 3.13 · uv · pydantic-settings · httpx · MCP-compatible HTTP contract

---

## Table of contents

- [The ShipSmart ecosystem](#the-shipsmart-ecosystem)
- [What this service does](#what-this-service-does)
- [HTTP contract](#http-contract)
- [Tools](#tools)
- [Architecture inside this service](#architecture-inside-this-service)
- [Configuration](#configuration)
- [Running locally](#running-locally)
- [Tests](#tests)
- [Observability](#observability)
- [Deployment (Render)](#deployment-render)
- [Consumers & cross-service contract](#consumers--cross-service-contract)
- [Operational notes](#operational-notes)
- [License](#license)

---

## The ShipSmart ecosystem

This service is one of six sibling repositories. Clone them as siblings
of this directory when working on the full system.

| Repo | Role | Stack |
|------|------|-------|
| [ShipSmart-Web](https://github.com/nia194/ShipSmart-Web) | React SPA — user-facing UI | React 19, Vite, TypeScript |
| [ShipSmart-Orchestrator](https://github.com/nia194/ShipSmart-Orchestrator) | Java transactional API — **single writer** to Supabase Postgres; quotes, bookings, saved options, carrier integration | Spring Boot 3.4, Java 17 |
| [ShipSmart-API](https://github.com/nia194/ShipSmart-API) | Python AI/orchestration service — RAG, advisors, recommendations, compliance (UC2), multi-agent workflow (UC3/UC4) | FastAPI, Python 3.13 |
| **[ShipSmart-MCP](https://github.com/nia194/ShipSmart-MCP)** _(this repo)_ | MCP tool server — `validate_address`, `get_quote_preview` (provider-pluggable) | FastAPI + MCP |
| [ShipSmart-Infra](https://github.com/nia194/ShipSmart-Infra) | Supabase migrations + edge functions, deployment configs, docs | Supabase, Render blueprints |
| [ShipSmart-Test](https://github.com/nia194/ShipSmart-Test) | Cross-repo integration harness — contract + live e2e suites, cross-service Postman collection | Python 3.13, pytest |

```
            ┌──────────────────────────────┐
            │       ShipSmart-Web          │
            │       React SPA · Vite       │
            └──────────────┬───────────────┘
                           │  Authorization: Bearer <Supabase JWT>
              ┌────────────┴────────────┐
              ▼                         ▼
┌──────────────────────────────┐   ┌──────────────────────────────┐
│  ShipSmart-Orchestrator      │◀──│        ShipSmart-API         │
│  Java / Spring Boot          │   │       Python / FastAPI       │
│  Sole writer to Postgres     │   │   RAG · advisors · recs      │
│  Carrier integration (FedEx) │   │                              │
└──────────────┬───────────────┘   └──────────────┬───────────────┘
               │                                  │
               │   X-MCP-Api-Key                  │   X-MCP-Api-Key
               │   (reserved — upcoming           │
               │    AI-assist flows)              │
               ▼                                  ▼
            ┌─────────────────────────────────────────┐
            │       ShipSmart-MCP (this repo)         │
            │       FastAPI · MCP HTTP contract       │
            │   validate_address · get_quote_preview  │
            └────────────────────┬────────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │  ShippingProvider (pluggable)│
                  │  mock · ups · fedex · dhl · usps │
                  └──────────────────────────────┘
```

The tool layer is centralized here — add a tool once, every service
gets it. The Java orchestrator's wiring (`SHIPSMART_MCP_URL` /
`SHIPSMART_MCP_API_KEY`) is in place but no Java call sites exist yet;
Python's `RemoteToolRegistry` hydrates from this server's `/tools/list`
on boot and routes every advisor/orchestration tool call through here.

---

## What this service does

| Capability | Endpoint | Notes |
|---|---|---|
| Service discovery | `GET /` | Name, version, tool count, endpoint map. Unauthenticated. |
| Liveness | `GET /health` | Probe used by Render's health check. Unauthenticated. |
| Tool catalog | `POST /tools/list` | Returns JSON Schemas for every registered tool. |
| Tool execution | `POST /tools/call` | Executes a tool by name with the provided arguments. |
| Interactive docs | `GET /docs`, `GET /redoc` | Swagger UI / ReDoc. Mounted only when `APP_ENV != production`. |

Wire-compatible with the
[MCP `tools/list` / `tools/call`](https://modelcontextprotocol.io/)
semantics: every call returns `{ success, content: [...], error? }`,
where `content` is a list of `{type, text}` blocks suitable for LLM
consumption.

---

## HTTP contract

| Method | Path          | Purpose                                                       |
| ------ | ------------- | ------------------------------------------------------------- |
| GET    | `/`           | Service discovery (name, version, tool count, endpoints).     |
| GET    | `/health`     | Liveness probe used by Render.                                |
| POST   | `/tools/list` | Return schemas for all registered tools.                      |
| POST   | `/tools/call` | Execute a tool by name with the provided arguments.           |
| GET    | `/docs`       | Swagger UI (non-production only).                             |
| GET    | `/redoc`      | ReDoc (non-production only).                                  |

### Auth

If `MCP_API_KEY` is set on the server, every `POST /tools/*` request
must send the matching value in `X-MCP-Api-Key`. If `MCP_API_KEY` is
empty, auth is disabled (local dev only). `GET /` and `GET /health` are
always unauthenticated so health checks and service discovery work
without the shared secret.

### Error responses

| Condition                                  | HTTP | Body                                                |
| ------------------------------------------ | ---- | --------------------------------------------------- |
| Missing or invalid `X-MCP-Api-Key`         | 401  | `{"detail": "Invalid or missing X-MCP-Api-Key"}`    |
| Unknown tool name                          | 404  | `{"detail": "Tool not found: <name>"}`              |
| Input validation failure or tool exception | 200  | `{"success": false, "content": [], "error": "..."}` |

Validation and execution errors deliberately return HTTP 200 with
`success=false` so consumers can distinguish protocol-level failures
(4xx) from tool-level failures (200 + `success=false`).

---

## Tools

| Name                | Description                                                                |
| ------------------- | -------------------------------------------------------------------------- |
| `validate_address`  | Validate + normalize a shipping address through the configured carrier.    |
| `get_quote_preview` | Non-binding rate preview for a package. Final rates come from the Java API.|

Tools delegate to pluggable `ShippingProvider` implementations selected
by `SHIPPING_PROVIDER`.

| Provider | Status                                                                  |
| -------- | ----------------------------------------------------------------------- |
| `mock`   | Fully working. Returns deterministic fake data for local dev and tests. |
| `ups`    | Stub — class exists but is not yet production-ready.                    |
| `fedex`  | Stub — class exists but is not yet production-ready.                    |
| `dhl`    | Stub — class exists but is not yet production-ready.                    |
| `usps`   | Stub — class exists but is not yet production-ready.                    |

Adding a tool is a matter of dropping a new class into `app/tools/` and
registering it in `app/main.py`.

### Provider startup behavior

- `SHIPPING_PROVIDER=mock` (default) emits a loud `WARNING` at startup
  so operators are not surprised by fake data.
- Selecting a real carrier (`ups` / `fedex` / `dhl` / `usps`) without
  all required credentials raises `ValueError` at startup. There is no
  silent fallback to mock — misconfiguration fails fast and visibly.

---

## Architecture inside this service

```
app/
├── main.py                  FastAPI app, tool registry wiring, lifespan, provider selection
├── core/
│   ├── config.py            pydantic-settings — env-driven configuration
│   └── middleware.py        RequestLoggingMiddleware (X-Request-Id + W3C traceparent)
├── tools/
│   ├── registry.py          ToolRegistry — `tools/list` + `tools/call` dispatch
│   ├── base.py              Tool ABC + JSON Schema helpers
│   ├── address_tools.py     validate_address
│   └── quote_tools.py       get_quote_preview
└── providers/
    ├── base.py              ShippingProvider ABC
    ├── shipping_provider.py Provider factory keyed by SHIPPING_PROVIDER
    ├── mock_provider.py     Deterministic fake data — local dev + tests
    ├── ups_provider.py      Stub
    ├── fedex_provider.py    Stub
    ├── dhl_provider.py      Stub
    └── usps_provider.py     Stub
```

The tool layer is decoupled from carrier implementations: each tool
calls into a `ShippingProvider` chosen at startup. New tools land in
`app/tools/` and register themselves with the `ToolRegistry`; new
carriers land in `app/providers/` and slot into the
`SHIPPING_PROVIDER` switch.

### Read-only least-privilege invariant

This server is strictly **read-only**: every tool it serves is a pure
read/preview operation (address validation, non-binding rate preview).
No tool or provider writes to a database, mutates persistent state,
moves money, or books anything — those actions belong exclusively to the
Java Orchestrator, the single writer of record. The invariant is
*enforced, not just documented*: `app/main.py` constrains the registry
to a `READ_ONLY_TOOL_ALLOWLIST` (`validate_address`, `get_quote_preview`)
and `_build_registry()` raises at startup if any tool outside that
allowlist is ever registered. Every tool input is also fully validated
against its JSON Schema *before* execution.

---

## Configuration

All settings are loaded from environment variables (or `.env` for local
dev). See [`.env.example`](./.env.example) for the full list and defaults.

| Variable                                  | Purpose                                                              |
| ----------------------------------------- | -------------------------------------------------------------------- |
| `APP_ENV`                                 | `development` or `production`. Gates `/docs` + `/redoc`.             |
| `APP_HOST` / `APP_PORT`                   | Bind address. Defaults `0.0.0.0:8001`.                               |
| `LOG_LEVEL`                               | Standard logging level (default `INFO`).                             |
| `CORS_ALLOWED_ORIGINS`                    | Comma-separated origins allowed by the CORS middleware.              |
| `MCP_API_KEY`                             | Shared secret enforced on `/tools/*`. Empty disables auth.           |
| `SHIPPING_SCOPE`                          | `worldwide` (default) or `domestic`. `domestic` makes `validate_address` reject any address outside `DOMESTIC_COUNTRY`. Mirrors ShipSmart-API's `SHIPPING_SCOPE`. |
| `DOMESTIC_COUNTRY`                        | ISO-3166 alpha-2 home country enforced when scope is `domestic` (default `US`). |
| `SHIPPING_PROVIDER`                       | One of `mock`, `ups`, `fedex`, `dhl`, `usps`.                        |
| `UPS_*` / `FEDEX_*` / `DHL_*` / `USPS_*`  | Per-carrier credentials and base URLs.                               |

---

## Running locally

### Prerequisites

- **Python 3.13+**
- [`uv`](https://docs.astral.sh/uv/) 0.6.5+

### Install & configure

```bash
cp .env.example .env
# fill in credentials if you want a real carrier integration;
# default is SHIPPING_PROVIDER=mock
uv sync
```

### Run

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Service comes up on `http://localhost:8001`. Browse the live OpenAPI
spec at `http://localhost:8001/docs` (development only).

### Smoke test

```bash
curl -s http://localhost:8001/health
curl -s -X POST http://localhost:8001/tools/list
curl -s -X POST http://localhost:8001/tools/call \
  -H 'Content-Type: application/json' \
  -d '{
        "name": "validate_address",
        "arguments": {
          "street":   "123 Main St",
          "city":     "San Francisco",
          "state":    "CA",
          "zip_code": "94105"
        }
      }'
```

If `MCP_API_KEY` is set, add `-H "X-MCP-Api-Key: $MCP_API_KEY"` to the
`/tools/*` calls.

### Postman collection

[`postman/ShipSmart-MCP.postman_collection.json`](./postman/ShipSmart-MCP.postman_collection.json)
walks the same contract with assertions on every request: discovery + liveness,
`tools/list`, a happy-path `tools/call` for both tools, and the error semantics
this README documents (unknown tool → `404`; schema-invalid input → `200` with
`success:false`, never a 4xx/5xx). Every request pins an `X-Request-Id`, and the
`/tools/*` requests already carry the `X-MCP-Api-Key` header — filling the
environment's `MCP_API_KEY` variable (empty by default for a no-auth local boot)
is all that auth needs. Import it with
[`postman/environments/local.postman_environment.json`](./postman/environments/local.postman_environment.json)
(`base_url` defaults to `http://127.0.0.1:8001`), or run it headless:

```bash
npx newman run postman/ShipSmart-MCP.postman_collection.json \
  -e postman/environments/local.postman_environment.json
```

---

## Tests

```bash
uv run pytest          # 95 tests, ~0.5s, no network
```

Tests live under `tests/` and use `pytest-asyncio` (async mode = auto). What they cover:

| File | Focus |
| --- | --- |
| `test_mcp_http.py` | The HTTP contract: `/health`, `/`, `/tools/list`, `/tools/call`, the `X-MCP-Api-Key` gate (and that liveness probes bypass it), schema validation rejecting malformed input *before* the provider runs, the read-only invariant, and execute-time errors mapping to `success=false` (HTTP 200, never a 500). |
| `test_schema_edge_cases.py` | Accepted/rejected JSON-Schema boundaries (ZIP+4, weight/dimension maxima, type coercion). |
| `test_tools.py` / `test_registry.py` | Tool execution + registry (dedup, sorting, schema shape). |
| `test_provider.py` / `test_provider_factory.py` | Mock provider behavior, the carrier factory (credential gating, case-insensitivity), and per-carrier `name`/DHL local validation. |

The tool schemas here are also asserted from `ShipSmart-Test/contract/` so a rename can't silently break ShipSmart-API or the Web client.

### Lint & formatting

```bash
uv run ruff check .          # lint (line length, imports, pyflakes)
```

A `.pre-commit-config.yaml` wires **ruff** plus hygiene hooks (end-of-file fixer, trailing
whitespace, YAML, merge-conflict) — install once with `uvx pre-commit install`. CI
(`.github/workflows/ci.yml`) runs `ruff check .` then `pytest -q` on every push / PR.

---

## Observability

`RequestLoggingMiddleware` (`app/core/middleware.py`) handles
correlation IDs for every request:

- Reads `X-Request-Id` from the inbound request, or mints a UUID hex if
  absent.
- Reads W3C `traceparent`, or mints a fresh one if absent or malformed.
- Echoes both headers on the response so callers can `grep` by ID
  across services.
- Emits one log line per request on the `shipsmart_mcp.requests`
  logger:

  ```
  GET /health → 200 (1.4ms) [a1b2c3...]
  ```

Pass `X-Request-Id` from upstream services to stitch a single request
across `ShipSmart-API` → MCP → carrier APIs. The Python service's
`outbound_headers()` helper already forwards both `X-Request-Id` and
`traceparent` on every MCP hop.

---

## Deployment (Render)

[`render.yaml`](./render.yaml) is a Render Blueprint defining the
deployed service:

- Python web service, build via `pip install uv && uv sync`, start via
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Health check at `/health`.
- `MCP_API_KEY` is `sync: false` — set it once in the Render dashboard
  and use the same value for every consumer's `SHIPSMART_MCP_API_KEY`.
- Default `SHIPPING_PROVIDER=fedex` pointing at
  `https://apis-sandbox.fedex.com` (FedEx **sandbox**, not production).
  Override the base URL when promoting to live carrier traffic.
- CORS origins are pinned in the blueprint to the deployed consumer
  URLs (`shipsmart-api-python`, `shipsmart-api-java`, `shipsmart-web`).

Provision by pointing Render at this repo; all `sync: false` env vars
must be filled before the first deploy succeeds.

The companion blueprints for the other services live alongside their
repos and in [ShipSmart-Infra](https://github.com/nia194/ShipSmart-Infra);
deploy them together when promoting a release.

---

## Consumers & cross-service contract

| Caller | Endpoint | Used by |
|---|---|---|
| **Python → MCP** | `POST /tools/list`, `POST /tools/call` | Every advisor and orchestration tool call. See `ShipSmart-API/app/services/mcp_client.py`. Auth via `X-MCP-Api-Key` when `SHIPSMART_MCP_API_KEY` is set. |
| **Java → MCP** | `POST /tools/list`, `POST /tools/call` | Reserved for upcoming AI-assist features. Wired via `shipsmart.mcp.base-url` / `SHIPSMART_MCP_URL`; no Java call sites yet. |
| **Ops / health** | `GET /` , `GET /health` | Render health probe + service discovery. Always unauthenticated. |

- **ShipSmart-API** (Python / FastAPI; deployed as
  `shipsmart-api-python` on Render): points `SHIPSMART_MCP_URL` at this
  server and calls `/tools/list` + `/tools/call` from its orchestration
  and advisor services. Tool catalog is hydrated at boot via
  `RemoteToolRegistry`.
- **ShipSmart-Orchestrator** (Java / Spring Boot; deployed as
  `shipsmart-api-java` on Render): will call the same HTTP contract
  from its upcoming AI-assist flows. No tool logic lives in the Java
  codebase.

When changing the tool surface, this repo is the source of truth.
Consumers should:

- **Python**: nothing to update for catalog changes — the registry
  re-hydrates from `/tools/list` on boot. For schema changes, update
  any callers in `app/services/orchestration_service.py` /
  `shipping_advisor_service.py` / `tracking_advisor_service.py`.
- **Java**: mirror the contract in whichever client lands when the
  AI-assist flows ship.

---

## Operational notes

- **`SHIPPING_PROVIDER=mock` warning on boot** — expected. The mock
  provider returns deterministic fake data; do not promote that
  configuration to production.
- **Server refuses to start with `ValueError` after carrier switch** —
  required credentials for the selected carrier are missing. There is
  no silent fallback to mock; fill in the matching `UPS_*` / `FEDEX_*` /
  `DHL_*` / `USPS_*` envs.
- **`401 Invalid or missing X-MCP-Api-Key`** — `MCP_API_KEY` is set on
  the server but the client did not send the matching header (or sent
  the wrong value). Confirm `SHIPSMART_MCP_API_KEY` on the consumer
  matches `MCP_API_KEY` here.
- **`404 Tool not found`** — the tool name in `/tools/call` does not
  match anything registered in `app/main.py`. Hit `POST /tools/list` to
  see the current catalog.
- **`200 { success: false }` from `/tools/call`** — protocol succeeded
  but the tool itself raised (validation failure, provider error). The
  `error` field has the detail; HTTP stays 200 by design so consumers
  can distinguish transport vs. tool failures.
- **`/docs` returns 404 in production** — expected. Swagger UI is
  mounted only when `APP_ENV != production`.
- **CORS blocked from a consumer** — add the calling origin to
  `CORS_ALLOWED_ORIGINS` (comma-separated). On Render, the blueprint
  already pins the three deployed consumers; override in the dashboard
  for additional origins.

---

## License

See [LICENSE](./LICENSE) for the full text.

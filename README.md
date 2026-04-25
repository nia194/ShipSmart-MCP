# ShipSmart-MCP

Standalone **MCP (Model Context Protocol) server** exposing ShipSmart's shipping
tools (`validate_address`, `get_quote_preview`, …) over a small HTTP contract.

It is the single source of truth for tool behavior across the platform. Both
`ShipSmart-API` (Python / FastAPI — RAG & LLMs) and `ShipSmart-Orchestrator`
(Java / Spring Boot — upcoming AI features) call this server instead of
implementing tools in-process.

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

Wire-compatible with the [MCP `tools/list` and `tools/call`](https://modelcontextprotocol.io/)
semantics: each call returns `{ success, content: [...], error? }`, where
`content` is a list of `{type, text}` blocks suitable for LLM consumption.

`/docs` and `/redoc` are mounted only when `APP_ENV != production`.

### Auth

If `MCP_API_KEY` is set on the server, every `POST /tools/*` request must
send the matching value in `X-MCP-Api-Key`. If `MCP_API_KEY` is empty, auth
is disabled (local dev only). `GET /` and `GET /health` are always
unauthenticated so health checks and service discovery work without the
shared secret.

### Error responses

| Condition                                  | HTTP | Body                                                |
| ------------------------------------------ | ---- | --------------------------------------------------- |
| Missing or invalid `X-MCP-Api-Key`         | 401  | `{"detail": "Invalid or missing X-MCP-Api-Key"}`    |
| Unknown tool name                          | 404  | `{"detail": "Tool not found: <name>"}`              |
| Input validation failure or tool exception | 200  | `{"success": false, "content": [], "error": "..."}` |

Validation and execution errors deliberately return HTTP 200 with
`success=false` so consumers can distinguish protocol-level failures (4xx)
from tool-level failures (200 + `success=false`).

---

## Tools

| Name                | Description                                                                |
| ------------------- | -------------------------------------------------------------------------- |
| `validate_address`  | Validate + normalize a shipping address through the configured carrier.    |
| `get_quote_preview` | Non-binding rate preview for a package. Final rates come from the Java API.|

Tools delegate to pluggable `ShippingProvider` implementations selected by
`SHIPPING_PROVIDER`.

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

- `SHIPPING_PROVIDER=mock` (default) emits a loud `WARNING` at startup so
  operators are not surprised by fake data.
- Selecting a real carrier (`ups`/`fedex`/`dhl`/`usps`) without all required
  credentials raises `ValueError` at startup. There is no silent fallback to
  mock — misconfiguration fails fast and visibly.

---

## Configuration

All settings are loaded from environment variables (or `.env` for local dev).
See `.env.example` for the full list and defaults.

| Variable               | Purpose                                                              |
| ---------------------- | -------------------------------------------------------------------- |
| `APP_ENV`              | `development` or `production`. Gates `/docs` + `/redoc`.             |
| `APP_HOST` / `APP_PORT`| Bind address. Defaults `0.0.0.0:8001`.                               |
| `LOG_LEVEL`            | Standard logging level (default `INFO`).                             |
| `CORS_ALLOWED_ORIGINS` | Comma-separated origins allowed by the CORS middleware.              |
| `MCP_API_KEY`          | Shared secret enforced on `/tools/*`. Empty disables auth.           |
| `SHIPPING_PROVIDER`    | One of `mock`, `ups`, `fedex`, `dhl`, `usps`.                        |
| `UPS_*` / `FEDEX_*` / `DHL_*` / `USPS_*` | Per-carrier credentials and base URLs.             |

---

## Running locally

Prerequisites: **Python 3.13+** and [`uv`](https://github.com/astral-sh/uv).

```bash
cp .env.example .env
# fill in credentials if you want real carrier integration; default is SHIPPING_PROVIDER=mock
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001
```

Smoke test:

```bash
curl -s http://localhost:8001/health
curl -s -X POST http://localhost:8001/tools/list
curl -s -X POST http://localhost:8001/tools/call \
  -H 'Content-Type: application/json' \
  -d '{
        "name": "validate_address",
        "arguments": {
          "street": "123 Main St",
          "city":   "San Francisco",
          "state":  "CA",
          "zip_code": "94105"
        }
      }'
```

## Tests

```bash
uv run pytest
```

---

## Observability

`RequestLoggingMiddleware` (`app/core/middleware.py`) handles correlation
IDs for every request:

- Reads `X-Request-Id` from the inbound request, or mints a UUID hex if
  absent.
- Reads W3C `traceparent`, or mints a fresh one if absent or malformed.
- Echoes both headers on the response so callers can `grep` by ID across
  services.
- Emits one log line per request on the `shipsmart_mcp.requests` logger:

  ```
  GET /health → 200 (1.4ms) [a1b2c3...]
  ```

Pass `X-Request-Id` from upstream services to stitch a single request
across `ShipSmart-API` → MCP → carrier APIs.

---

## Deployment (Render)

`render.yaml` is a Render Blueprint defining the deployed service:

- Python web service, build via `pip install uv && uv sync`, start via
  `uvicorn app.main:app --host 0.0.0.0 --port $PORT`.
- Health check at `/health`.
- `MCP_API_KEY` is `sync: false` — set it once in the Render dashboard and
  use the same value for every consumer's `SHIPSMART_MCP_API_KEY`.
- Default `SHIPPING_PROVIDER=fedex` pointing at `https://apis-sandbox.fedex.com`
  (FedEx **sandbox**, not production). Override the base URL when promoting
  to live carrier traffic.
- CORS origins are pinned in the blueprint to the deployed consumer URLs.

Provision by pointing Render at this repo; all `sync: false` env vars must
be filled before the first deploy succeeds.

---

## Consumers

- **ShipSmart-API** (Python / FastAPI; deployed as `shipsmart-api-python` on
  Render): points `SHIPSMART_MCP_URL` at this server and calls
  `/tools/list` + `/tools/call` from its orchestration and advisor services.
- **ShipSmart-Orchestrator** (Java / Spring Boot; deployed as
  `shipsmart-api-java` on Render): will call the same HTTP contract from
  its upcoming AI-assist flows. No tool logic lives in the Java codebase.

This keeps the tool layer centralized — add a tool once, every service gets it.

# ShipSmart-MCP

Standalone **MCP (Model Context Protocol) server** exposing ShipSmart's shipping
tools (`validate_address`, `get_quote_preview`, …) over a small HTTP contract.

It is the single source of truth for tool behavior across the platform. Both
`ShipSmart-API` (Python / FastAPI — RAG & LLMs) and `ShipSmart-Orchestrator`
(Java / Spring Boot — upcoming AI features) call this server instead of
implementing tools in-process.

---

## HTTP contract

| Method | Path          | Purpose                                                      |
| ------ | ------------- | ------------------------------------------------------------ |
| GET    | `/`           | Service discovery (name, version, tool count, endpoints).    |
| GET    | `/health`     | Liveness probe used by Render.                               |
| POST   | `/tools/list` | Return schemas for all registered tools.                     |
| POST   | `/tools/call` | Execute a tool by name with the provided arguments.          |

Wire-compatible with the [MCP `tools/list` and `tools/call`](https://modelcontextprotocol.io/)
semantics: each call returns `{ success, content: [...], error? }`, where
`content` is a list of `{type, text}` blocks suitable for LLM consumption.

### Auth

If `MCP_API_KEY` is set on the server, every `POST /tools/*` request must
send the matching value in `X-MCP-Api-Key`. If `MCP_API_KEY` is empty, auth
is disabled (local dev only).

---

## Tools

| Name                | Description                                                               |
| ------------------- | ------------------------------------------------------------------------- |
| `validate_address`  | Validate + normalize a shipping address through the configured carrier.   |
| `get_quote_preview` | Non-binding rate preview for a package. Final rates come from the Java API.|

Tools delegate to pluggable `ShippingProvider` implementations
(`mock`, `ups`, `fedex`, `dhl`, `usps`) selected by `SHIPPING_PROVIDER`.
Adding a tool is a matter of dropping a new class into `app/tools/` and
registering it in `app/main.py`.

---

## Running locally

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

## Consumers

- **ShipSmart-API** (Python/FastAPI): points `SHIPSMART_MCP_URL` at the deployed
  server and calls `/tools/list` + `/tools/call` from its orchestration and
  advisor services.
- **ShipSmart-Orchestrator** (Java/Spring Boot): will call the same HTTP
  contract from its upcoming AI-assist flows. No tool logic lives in the Java
  codebase.

This keeps the tool layer centralized — add a tool once, every service gets it.

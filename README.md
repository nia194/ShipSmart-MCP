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

> **Metric convention:** structural counts (tools, tests, endpoints) are facts
> verified against source; latency/availability figures are **(target)**
> budgets, never measured production metrics.

---

## Table of contents

- [The ShipSmart ecosystem](#the-shipsmart-ecosystem)
- [Architecture (HLD)](#architecture-hld)
- [The headline invariant](#the-headline-invariant)
- [HTTP contract](#http-contract)
- [Anatomy of a tool call](#anatomy-of-a-tool-call)
- [Tools](#tools)
- [Object design (OOD)](#object-design-ood)
- [Security layers & threat model](#security-layers--threat-model)
- [The audit trail](#the-audit-trail)
- [Performance & availability](#performance--availability)
- [Deployment topology](#deployment-topology)
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

## Architecture (HLD)

**Figure 1 — container/component view.** Every call crosses the guard/audit/
integrity plane before any carrier adapter runs; the registry's JSON Schemas
power both discovery and enforcement.

```mermaid
flowchart TB
    API["ShipSmart-API (agent / RAG / concierge)"] -->|"MCP over HTTP + X-MCP-Api-Key"| APP
    subgraph APP["FastAPI app (app/main.py)"]
        AUTH["require_api_key dependency"]
        EP["GET / · GET /health · POST /tools/list · POST /tools/call"]
        INV["_enforce_read_only(registry) at lifespan"]
    end
    subgraph REG["ToolRegistry (app/tools)"]
        T1[validate_address]
        T2[get_quote_preview]
        T3[calculate_dimensional_weight]
        T4[estimate_package_profile]
        T5[parse_address]
        T6[check_restricted_items]
    end
    subgraph CTL["Cross-cutting controls"]
        JS["JSON Schema 2020-12 validate_input (additionalProperties=false)"]
        TG["tool_guard: SSRF egress allowlist + per-caller scopes"]
        TA["tool_audit: append-only, args-hashed"]
        IN["integrity: sha256 descriptor checksums"]
    end
    subgraph PROV["Provider adapters (Strategy)"]
        P0["MockProvider (keyless default)"]
        P1[FedExProvider]
        P2[UPSProvider]
        P3[USPSProvider]
        P4[DHLProvider]
    end
    CARR["Carrier REST APIs (sandbox base URLs)"]
    APP --> REG
    REG --> CTL
    REG --> PROV
    PROV -->|"httpx, explicit timeouts"| CARR
```

**Patterns:** Adapter/Strategy (one `ShippingProvider` port, five adapters) ·
Registry (discovery + lookup) · least privilege as a **boot invariant** · Guard
(egress + caller scopes) · content-addressable integrity (descriptor checksums).

---

## The headline invariant

`READ_ONLY_TOOL_ALLOWLIST` is a **`frozenset`**, and `_enforce_read_only()`
runs at startup:

```
Refusing to start: non-read-only tool(s) registered: [...].
ShipSmart-MCP serves read/preview tools only; writes, bookings, and
money movement belong to the Java Orchestrator.
```

**Figure 2 — least privilege as a boot-time property.** A developer who
registers a write tool can't even start the service — the mistake fails loudly
in dev and CI, never silently in production.

```mermaid
flowchart TB
    S[Service starting] --> B["_build_registry()"]
    B --> E["_enforce_read_only(registry)"]
    E --> C{"served tools ⊆ READ_ONLY_TOOL_ALLOWLIST?"}
    C -->|yes| UP["App serves traffic"]
    C -->|no| X["raise RuntimeError — refuse to start"]
    X --> MSG["writes, bookings, money movement belong to the Java Orchestrator"]
```

---

## HTTP contract

| Endpoint | Purpose |
|---|---|
| `GET /` | discovery/info |
| `GET /health` | service + registered tool count |
| `POST /tools/list` | MCP discovery — full JSON Schemas per tool |
| `POST /tools/call` | execute one tool (auth + validation + guard + audit) |

`X-MCP-Api-Key` (shared key) gates the tool routes — this is an internal
service, called by the API, never by browsers.

---

## Anatomy of a tool call

**Figure 3 — `/tools/call` happy path: five controls in order.**

```mermaid
sequenceDiagram
    participant C as Caller (ShipSmart-API)
    participant A as FastAPI (require_api_key)
    participant R as ToolRegistry
    participant G as tool_guard
    participant P as Provider adapter
    participant AU as tool_audit
    C->>A: POST /tools/call (X-MCP-Api-Key)
    A->>R: lookup(tool)
    R->>R: validate_input (JSON Schema 2020-12)
    R->>G: is_authorized(caller, tool)? egress allowed?
    G-->>R: allowed
    R->>P: execute(args)
    P->>P: httpx call, explicit timeout
    P-->>R: read-only result
    R->>AU: record(tool, caller, request_id, args_hash, status, latency_ms)
    R-->>C: typed result
```

**Figure 4 — SSRF denial: blocked before any network I/O.** The same guard
denies any non-allowlisted host and every private/loopback/link-local IP
literal (the cloud metadata-endpoint attack).

```mermaid
sequenceDiagram
    participant T as Tool execution
    participant G as tool_guard
    T->>G: assert_egress_allowed("http://169.254.169.254/...")
    G->>G: _is_public? link-local IP literal detected
    G--xT: EgressDeniedError (no request ever leaves)
```

**Figure 5 — schema rejection & descriptor drift: both fail closed.**

```mermaid
sequenceDiagram
    participant C as Caller
    participant R as Registry
    participant I as integrity
    C->>R: tools/call with unexpected field
    R--xC: validation error (additionalProperties=false, before execute())
    C->>I: verify_descriptors(registry, expected_checksums)
    I-->>C: drift list (changed / added / removed descriptors)
    Note over I: sha256 over name + description + input schema
```

**Figure 6 — tool-call lifecycle (state machine).** Every terminal state —
success, failure, or denial — passes through the audit before the response
leaves.

```mermaid
stateDiagram-v2
    [*] --> Received: POST /tools/call
    Received --> Authenticated: X-MCP-Api-Key ok
    Received --> Rejected: bad or missing key (401)
    Authenticated --> Validated: JSON Schema ok
    Authenticated --> Rejected: unknown or invalid args
    Validated --> Guarded: caller in scope AND egress allowed
    Validated --> Denied: off-scope or EgressDenied
    Guarded --> Executing: adapter call (timeout armed)
    Executing --> Succeeded: carrier or pure result
    Executing --> Failed: timeout or carrier error
    Succeeded --> Audited: args-hashed record
    Failed --> Audited: error_class recorded
    Denied --> Audited
    Audited --> [*]
```

---

## Tools

| Tool | Kind | Honest semantics |
|---|---|---|
| `validate_address` | carrier-backed | deliverability / normalization |
| `get_quote_preview` | carrier-backed | **preview** pricing — never bookable |
| `calculate_dimensional_weight` | pure | billable = max(actual, L·W·H ÷ divisor) |
| `estimate_package_profile` | pure | labelled profile → estimated dims, `is_estimate` flagged |
| `parse_address` | pure | freeform → components + rule-derived confidence; **reports missing parts, never guesses** |
| `check_restricted_items` | corpus-backed | allowed/warning/prohibited + source; **advisory-only — never asserts "cleared"** |

---

## Object design (OOD)

**Figure 7 — class model.** Tools depend on the provider **port**, never a
concrete carrier — adding a carrier is a new adapter; the tool layer is
untouched.

```mermaid
classDiagram
    class Tool {
        <<abstract>>
        +name
        +description
        +parameters
        +schema() JSONSchema2020_12
        +validate_input(args)
        +execute(args)
    }
    Tool <|-- ValidateAddress
    Tool <|-- GetQuotePreview
    Tool <|-- CalculateDimensionalWeight
    Tool <|-- EstimatePackageProfile
    Tool <|-- ParseAddress
    Tool <|-- CheckRestrictedItems
    class ToolRegistry {
        +list_tools()
        +get(name)
    }
    ToolRegistry o-- Tool
    class ShippingProvider {
        <<interface>>
        +validate_address()
        +quote_preview()
    }
    ShippingProvider <|.. MockProvider
    ShippingProvider <|.. FedExProvider
    ShippingProvider <|.. UPSProvider
    ShippingProvider <|.. USPSProvider
    ShippingProvider <|.. DHLProvider
    GetQuotePreview ..> ShippingProvider
    ValidateAddress ..> ShippingProvider
    class ToolGuard {
        +allowed_hosts()
        +check_egress(url)
        +is_authorized(caller, tool)
    }
    class ToolAudit {
        +args_hash(args) sha256
        +record(...)
    }
```

---

## Security layers & threat model

Five independent controls stack on every call:

1. **Shared-key auth** — `require_api_key` (`X-MCP-Api-Key`).
2. **SSRF egress allowlist** — allowlisted carrier hosts only;
   private/loopback/link-local IP literals denied before any I/O.
3. **Per-caller tool scopes** — off-scope tools are denied, not merely hidden.
4. **Descriptor integrity** — sha256 checksums make registry drift detectable.
5. **Append-only, args-hashed audit** — full observability, no PII store.

| Threat | Control |
|---|---|
| Unauthenticated access | shared-key `X-MCP-Api-Key` on tool routes |
| SSRF / metadata endpoint | egress allowlist + private-IP denial |
| Caller privilege creep | per-caller tool scopes |
| Poisoned tool descriptors (supply chain) | sha256 checksums + `verify_descriptors` |
| PII in audit | args-hash, never raw args |
| Write capability smuggled in | frozen allowlist + boot-time `RuntimeError` |

---

## The audit trail

**Figure 8 — one PII-safe record per call.** Raw arguments (which may carry
addresses) are never stored — only their hash, which still allows exact-call
correlation.

```mermaid
flowchart LR
    CALL["tools/call"] --> H["args_hash = sha256(args)"]
    H --> REC["record: tool · version · caller · request_id · args_hash · status · error_class · latency_ms"]
    REC --> LOG[("append-only tool audit")]
    LOG --> Q["what did the tool layer do, for whom, how fast = a query"]
```

---

## Performance & availability

*(This service is stateless — it owns no database, so there is no
entity-relationship model here; the platform's ER story lives in
[ShipSmart-Infra](https://github.com/nia194/ShipSmart-Infra).)*

**Latency budget (target):**

| Tool | Validation | Carrier RTT | Total *(target)* |
|---|---|---|---|
| pure tools (×3) | ~2 ms | — | **< 10 ms** |
| validate_address | ~2 ms | 300–1500 ms | **< 2000 ms** |
| get_quote_preview | ~2 ms | 300–1800 ms | **< 2000 ms** |

```mermaid
xychart-beta
    title "Tool latency budget in ms (target)"
    x-axis ["pure-tools", "validate_address", "quote_preview"]
    y-axis "ms (target)" 0 --> 2000
    bar [10, 1200, 1800]
```

**Availability & degradation (coded behaviors, facts):**

| Failure | Behavior |
|---|---|
| Carrier timeout | explicit httpx timeout → typed error, `error_class` audited |
| No carrier keys | MockProvider default — fully functional, keyless |
| Bad caller key | 401 at `require_api_key` — tools never execute |
| Off-scope caller | denied by `tool_guard` scopes |

Availability **99.5% (target)**; probes: `GET /health` (the tool count doubles
as a registry-drift canary) and `GET /` discovery.

---

## Deployment topology

**Figure 9 — production layout.** Called only by the API; `/docs` off in prod;
sandbox carrier base URLs by default.

```mermaid
flowchart LR
    A["Render: shipsmart-api-python"] -->|X-MCP-Api-Key| M["Render: shipsmart-mcp (this)"]
    M --> C1["FedEx sandbox"]
    M --> C2["UPS sandbox"]
    M --> C3["USPS sandbox"]
    M --> C4["DHL sandbox"]
    OPS[Operator] -.->|"GET /health — tool count"| M
```

---

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

"""
ShipSmart-MCP — FastAPI MCP (Model Context Protocol) server.

Exposes ShipSmart's shipping tools (validate_address, get_quote_preview, ...)
over a small HTTP contract compatible with MCP tools/list + tools/call
semantics. Consumers: ShipSmart-API (Python) and ShipSmart-Orchestrator (Java).

Local dev:
    uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8001

Production (Render):
    uvicorn app.main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.providers import create_shipping_provider
from app.tools.address_tools import ValidateAddressTool
from app.tools.base import ToolInput, ToolOutput
from app.tools.quote_tools import GetQuotePreviewTool
from app.tools.registry import ToolRegistry

setup_logging()
logger = get_logger(__name__)


# ── Registry lifecycle ───────────────────────────────────────────────────────

_tool_registry: ToolRegistry | None = None


def _build_registry() -> ToolRegistry:
    """Build the tool registry with the configured shipping provider.

    Kept module-level so tests can re-invoke it after monkey-patching
    environment variables.
    """
    registry = ToolRegistry()
    provider = create_shipping_provider()
    registry.register(ValidateAddressTool(provider))
    registry.register(GetQuotePreviewTool(provider))
    return registry


def get_tool_registry() -> ToolRegistry:
    """Return the live registry, creating it lazily on first access."""
    global _tool_registry
    if _tool_registry is None:
        _tool_registry = _build_registry()
        logger.info("Tool registry initialized with %d tools", _tool_registry.count())
    return _tool_registry


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the registry at startup so first-request latency is predictable."""
    logger.info(
        "Starting %s v%s in '%s' mode",
        settings.app_name, settings.app_version, settings.app_env,
    )
    registry = get_tool_registry()
    logger.info(
        "MCP server ready with %d tools; auth=%s",
        registry.count(),
        "on" if settings.mcp_api_key else "off",
    )
    yield
    logger.info("Shutting down %s", settings.app_name)


# ── Auth dependency ──────────────────────────────────────────────────────────

def require_api_key(
    x_mcp_api_key: str | None = Header(default=None, alias="X-MCP-Api-Key"),
) -> None:
    """Enforce X-MCP-Api-Key when settings.mcp_api_key is configured.

    If mcp_api_key is empty, the check is a no-op so local dev works without
    setting up a shared secret.
    """
    expected = settings.mcp_api_key
    if not expected:
        return
    if not x_mcp_api_key or x_mcp_api_key != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing X-MCP-Api-Key")


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="ShipSmart MCP Server",
    description=(
        "MCP server exposing ShipSmart shipping tools "
        "(validate_address, get_quote_preview) for ShipSmart-API and "
        "ShipSmart-Orchestrator."
    ),
    version=settings.app_version,
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)

from app.core.middleware import RequestLoggingMiddleware

app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*", "X-MCP-Api-Key"],
)


# ── Schemas ──────────────────────────────────────────────────────────────────

class MCPToolDefinition(BaseModel):
    """MCP tool definition (compatible with Claude API)."""
    name: str
    description: str
    input_schema: dict[str, Any]


class MCPToolListResponse(BaseModel):
    tools: list[MCPToolDefinition]


class MCPToolCallRequest(BaseModel):
    name: str
    arguments: dict[str, Any]


class MCPToolCallResponse(BaseModel):
    success: bool
    content: list[dict[str, Any]]
    error: str | None = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": settings.app_name,
        "version": settings.app_version,
        "tools": get_tool_registry().count(),
    }


@app.get("/")
async def root():
    registry = get_tool_registry()
    return {
        "name": "ShipSmart MCP Server",
        "version": settings.app_version,
        "description": "MCP server for ShipSmart tools",
        "tools_count": registry.count(),
        "endpoints": {
            "health": "/health",
            "tools_list": "/tools/list (POST)",
            "tools_call": "/tools/call (POST)",
        },
    }


@app.post("/tools/list", dependencies=[Depends(require_api_key)])
async def list_tools() -> MCPToolListResponse:
    """Return MCP-compatible schemas for every registered tool."""
    registry = get_tool_registry()
    tools = registry.list_tools()

    tool_definitions: list[MCPToolDefinition] = []
    for tool in tools:
        schema = tool.schema()

        properties: dict[str, dict[str, Any]] = {}
        required: list[str] = []
        for param in tool.parameters:
            properties[param.name] = {
                "type": param.type,
                "description": param.description,
            }
            if param.required:
                required.append(param.name)

        input_schema = {
            "type": "object",
            "properties": properties,
            "required": required,
        }

        tool_definitions.append(
            MCPToolDefinition(
                name=schema["name"],
                description=schema["description"],
                input_schema=input_schema,
            )
        )

    logger.info("Listed %d tools", len(tool_definitions))
    return MCPToolListResponse(tools=tool_definitions)


@app.post("/tools/call", dependencies=[Depends(require_api_key)])
async def call_tool(request: MCPToolCallRequest) -> MCPToolCallResponse:
    """Execute a named tool and return its result as MCP content blocks."""
    registry = get_tool_registry()
    tool = registry.get(request.name)

    if tool is None:
        logger.error("Tool not found: %s", request.name)
        raise HTTPException(status_code=404, detail=f"Tool not found: {request.name}")

    errors = tool.validate_input(request.arguments)
    if errors:
        logger.warning("Validation failed for %s: %s", request.name, errors)
        return MCPToolCallResponse(
            success=False,
            content=[],
            error="; ".join(errors),
        )

    try:
        logger.info("Executing tool: %s", request.name)
        result: ToolOutput = await tool.execute(ToolInput(params=request.arguments))
    except Exception as exc:
        logger.error("Tool execution failed: %s", exc, exc_info=True)
        return MCPToolCallResponse(success=False, content=[], error=str(exc))

    content: list[dict[str, Any]] = []
    if result.success:
        content.append({"type": "text", "text": json.dumps(result.data, indent=2)})
    else:
        content.append({"type": "text", "text": f"Error: {result.error}"})

    if result.metadata:
        content.append(
            {"type": "text", "text": f"Metadata: {json.dumps(result.metadata, indent=2)}"}
        )

    logger.info(
        "Tool execution completed: %s (success=%s)", request.name, result.success
    )

    return MCPToolCallResponse(
        success=result.success,
        content=content,
        error=result.error,
    )

"""Tool audit log (Governance & Guardrails §5.5).

One append-only record per tool call — tool, version, caller, request_id, a
**hash** of the arguments (never the raw args, which may carry PII like an
address), status, and latency. Makes "what did the tool layer do, for whom" a
query. Best-effort (auditing never breaks a call); a durable backend is a future
adapter. Mirrors the ShipSmart-API audit sink pattern.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger("shipsmart_mcp.tool_audit")


def args_hash(args: dict[str, Any]) -> str:
    """Stable sha256 of tool args (so audit carries no raw PII)."""
    return sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()[:16]


@dataclass(frozen=True)
class ToolAuditRecord:
    tool: str
    version: str = "v1"
    caller: str = ""
    request_id: str = ""
    args_hash: str = ""
    status: str = "ok"            # ok | error | denied
    latency_ms: float = 0.0
    ts: str = ""

    def __post_init__(self) -> None:
        if not self.ts:
            object.__setattr__(self, "ts", datetime.now(tz=UTC).isoformat())


@runtime_checkable
class ToolAuditSink(Protocol):
    def emit(self, record: ToolAuditRecord) -> None: ...


class LoggingToolAuditSink:
    def emit(self, record: ToolAuditRecord) -> None:
        try:
            logger.info("tool_audit %s", record.__dict__)
        except Exception:  # noqa: BLE001 - auditing must never break a call
            pass


class InMemoryToolAuditSink:
    def __init__(self) -> None:
        self._records: list[ToolAuditRecord] = []

    def emit(self, record: ToolAuditRecord) -> None:
        self._records.append(record)

    @property
    def records(self) -> list[ToolAuditRecord]:
        return list(self._records)


def create_tool_audit_sink(kind: str = "logging") -> ToolAuditSink:
    if (kind or "logging").strip().lower() == "memory":
        return InMemoryToolAuditSink()
    return LoggingToolAuditSink()


def record_tool_call(
    sink: ToolAuditSink,
    *,
    tool: str,
    args: dict[str, Any] | None = None,
    version: str = "v1",
    caller: str = "",
    request_id: str = "",
    status: str = "ok",
    latency_ms: float = 0.0,
) -> ToolAuditRecord:
    """Build + emit a PII-safe (args-hashed) tool-audit record (best-effort)."""
    record = ToolAuditRecord(
        tool=tool,
        version=version,
        caller=caller,
        request_id=request_id,
        args_hash=args_hash(args or {}),
        status=status,
        latency_ms=latency_ms,
    )
    sink.emit(record)
    return record

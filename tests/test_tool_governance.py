"""Tool descriptor integrity + tool audit (guardrails §5.5)."""

from __future__ import annotations

from app.core.tool_audit import (
    InMemoryToolAuditSink,
    args_hash,
    create_tool_audit_sink,
    record_tool_call,
)
from app.tools.base import Tool, ToolInput, ToolOutput, ToolParameter
from app.tools.integrity import descriptor_checksum, registry_checksums, verify_descriptors
from app.tools.registry import ToolRegistry


class _FakeTool(Tool):
    def __init__(self, name: str, desc: str = "does a thing") -> None:
        self._name, self._desc = name, desc

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._desc

    @property
    def parameters(self) -> list[ToolParameter]:
        return [ToolParameter(name="zip_code", type="string", description="ZIP")]

    async def execute(self, tool_input: ToolInput) -> ToolOutput:  # pragma: no cover
        return ToolOutput(success=True)


def _registry(*tools: Tool) -> ToolRegistry:
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


def test_descriptor_checksum_is_deterministic_and_content_sensitive():
    a = descriptor_checksum(_FakeTool("validate_address"))
    assert a == descriptor_checksum(_FakeTool("validate_address"))       # stable
    assert a != descriptor_checksum(_FakeTool("validate_address", "changed desc"))  # sensitive


def test_verify_descriptors_detects_no_drift_when_pinned():
    reg = _registry(_FakeTool("validate_address"), _FakeTool("get_quote_preview"))
    pinned = registry_checksums(reg)
    assert verify_descriptors(reg, pinned) == []


def test_verify_descriptors_flags_changed_missing_and_unexpected():
    reg = _registry(_FakeTool("validate_address"), _FakeTool("get_quote_preview"))
    pinned = registry_checksums(reg)
    # tamper: a changed descriptor + a missing tool + an unexpected new tool
    tampered = _registry(_FakeTool("validate_address", "MALICIOUS"), _FakeTool("rogue_tool"))
    findings = verify_descriptors(tampered, pinned)
    assert any("descriptor changed: validate_address" in f for f in findings)
    assert any("missing tool: get_quote_preview" in f for f in findings)
    assert any("unexpected tool: rogue_tool" in f for f in findings)


def test_tool_audit_hashes_args_and_is_append_only():
    sink = InMemoryToolAuditSink()
    rec = record_tool_call(
        sink, tool="validate_address", args={"zip_code": "94105"}, request_id="r1"
    )
    # args are hashed, never stored raw
    assert rec.args_hash and "94105" not in rec.args_hash
    assert rec.args_hash == args_hash({"zip_code": "94105"})
    record_tool_call(sink, tool="get_quote_preview", args={}, status="ok")
    assert [r.tool for r in sink.records] == ["validate_address", "get_quote_preview"]


def test_audit_sink_factory_and_logging_never_raises():
    assert isinstance(create_tool_audit_sink("memory"), InMemoryToolAuditSink)
    # logging sink is best-effort — emitting must never raise
    record_tool_call(create_tool_audit_sink("logging"), tool="t", args={"a": 1})

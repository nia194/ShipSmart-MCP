"""Freeform address parsing (Product Roadmap §11 backlog — P2).

A read-only, deterministic tool that turns a freeform address string into
structured components + a rule-derived confidence, so the assistant can propose
a form patch the apply-policy gate can reason about. It NEVER silently assumes a
location — a low-confidence parse surfaces missing components for the UI to ask
about ("Use Atlanta?"), it does not guess.

Heuristic + US-centric today; a fuller parser is a provider swap behind the same
tool name (the point is the typed seam, not a perfect geocoder).
"""

from __future__ import annotations

import re
from typing import Any

from app.tools.base import Tool, ToolInput, ToolOutput, ToolParameter

# US state abbreviations + a couple of country hints for a light country guess.
_US_STATES = frozenset(
    """AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO
    MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC""".split()
)
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_STATE_RE = re.compile(r"\b([A-Z]{2})\b")


class ParseAddressTool(Tool):
    """Freeform address string → {street, city, state, postal_code, country} + confidence."""

    @property
    def name(self) -> str:
        return "parse_address"

    @property
    def description(self) -> str:
        return (
            "Parse a freeform address into structured components with a confidence "
            "score. Low confidence returns the missing components — it never guesses a location."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [ToolParameter("address", "string", "Freeform address text")]

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {"address": {"type": "string", "minLength": 1, "maxLength": 300}},
            "required": ["address"],
            "additionalProperties": False,
        }

    async def execute(self, tool_input: ToolInput) -> ToolOutput:
        raw = str(tool_input.params["address"]).strip()
        parts = [p.strip() for p in raw.split(",") if p.strip()]

        postal = None
        state = None
        zip_match = _ZIP_RE.search(raw)
        if zip_match:
            postal = zip_match.group(1)
        # Only STANDALONE two-letter tokens count as a state ("IL"), never a slice
        # of a longer word ("MA" inside "Main").
        for token in re.findall(r"\b([A-Za-z]{2})\b", raw):
            if token.upper() in _US_STATES:
                state = token.upper()
                break

        street = parts[0] if parts else None
        city = None
        if len(parts) >= 2:
            # City is the segment before the one carrying state/zip (or the 2nd part).
            city_candidate = parts[1]
            city = _STATE_RE.sub("", _ZIP_RE.sub("", city_candidate)).strip() or None
        country = "US" if (state or postal) else None

        components = {
            "street": street,
            "city": city,
            "state": state,
            "postal_code": postal,
            "country": country,
        }
        present = [k for k, v in components.items() if v]
        missing = [k for k, v in components.items() if not v]
        confidence = round(len(present) / len(components), 2)

        return ToolOutput(
            success=True,
            data={
                "components": components,
                "confidence": confidence,
                "missing": missing,
                "is_complete": not missing,
            },
            metadata={"note": "heuristic parse; confirm before using as a location"},
        )

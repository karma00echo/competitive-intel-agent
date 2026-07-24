"""Offline JSON-backed fact extraction provider."""

from __future__ import annotations

import json
from pathlib import Path

from competitive_intel.domain.facts import CandidateFact, FactCategory
from competitive_intel.domain.urls import normalize_url

from .base import FactExtractionRequest, FactExtractionResponse


DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "facts" / "facts.json"
)


class FixtureFactExtractionProvider:
    def __init__(self, fixture_path: str | Path | None = None) -> None:
        path = Path(fixture_path) if fixture_path else DEFAULT_FIXTURE
        self._data = json.loads(path.read_text(encoding="utf-8"))
        self.calls: list[FactExtractionRequest] = []

    @property
    def name(self) -> str:
        return "fixture"

    def extract(self, request: FactExtractionRequest) -> FactExtractionResponse:
        self.calls.append(request)
        rows = self._data["pages"].get(normalize_url(request.source_url))
        if rows is None:
            return FactExtractionResponse(
                (), self.name, "fixture-v1", f"fixture-{request.snapshot_id}",
                {"input_characters": len(request.clean_content), "output_facts": 0},
                error=f"No fact fixture for {request.source_url}",
            )
        allowed = set(request.allowed_fact_categories)
        eligible = tuple(
            CandidateFact(
                fact_category=FactCategory(row["fact_category"]),
                fact_value=row["fact_value"],
                value_text=row["value_text"],
                evidence_text=row["evidence_text"],
                confidence=float(row["confidence"]),
                statement_type=row.get("statement_type", "FACT"),
                extraction_warnings=tuple(row.get("extraction_warnings", [])),
            )
            for row in rows
            if FactCategory(row["fact_category"]) in allowed
        )
        candidates = eligible[: request.max_facts]
        warnings = (
            ("Fact limit reached; remaining fixture candidates were not returned.",)
            if len(eligible) > request.max_facts else ()
        )
        return FactExtractionResponse(
            candidates, self.name, "fixture-v1", f"fixture-{request.snapshot_id}",
            {"input_characters": len(request.clean_content), "output_facts": len(candidates)},
            warnings=warnings,
        )

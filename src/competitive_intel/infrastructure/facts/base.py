"""Provider-neutral structured fact extraction contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from competitive_intel.domain.facts import CandidateFact, FactCategory


@dataclass(frozen=True, slots=True)
class FactExtractionRequest:
    competitor_name: str
    source_type: str
    source_url: str
    snapshot_id: int
    clean_content: str
    allowed_fact_categories: tuple[FactCategory, ...]
    fact_schema: dict[str, Any]
    max_facts: int


@dataclass(frozen=True, slots=True)
class FactExtractionResponse:
    candidate_facts: tuple[CandidateFact, ...]
    provider: str
    model: str
    request_id: str
    usage: dict[str, int]
    warnings: tuple[str, ...] = ()
    error: str | None = None


class FactExtractionProvider(Protocol):
    @property
    def name(self) -> str: ...

    def extract(self, request: FactExtractionRequest) -> FactExtractionResponse: ...

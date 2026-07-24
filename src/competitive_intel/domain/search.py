"""Provider-neutral search contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SearchIntent(StrEnum):
    OFFICIAL_SITE = "OFFICIAL_SITE"
    FEATURES = "FEATURES"
    PRICING = "PRICING"
    CHANGELOG = "CHANGELOG"


@dataclass(frozen=True, slots=True)
class SearchRequest:
    query: str
    intent: SearchIntent
    locale: str = "en-US"
    language: str = "en"
    limit: int = 10

    def __post_init__(self) -> None:
        if not self.query.strip():
            raise ValueError("query must not be empty")
        if not 1 <= self.limit <= 50:
            raise ValueError("limit must be between 1 and 50")


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str
    rank: int
    provider: str
    query: str


@dataclass(frozen=True, slots=True)
class SearchResponse:
    request: SearchRequest
    results: tuple[SearchResult, ...]
    provider: str
    error_code: str | None = None
    error_message: str | None = None

    @property
    def ok(self) -> bool:
        return self.error_code is None

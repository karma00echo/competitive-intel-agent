"""Offline JSON-backed search provider."""

from __future__ import annotations

import json
from pathlib import Path

from competitive_intel.domain.search import (
    SearchRequest,
    SearchResponse,
    SearchResult,
)


DEFAULT_FIXTURE = (
    Path(__file__).resolve().parents[5] / "tests" / "fixtures" / "search" / "results.json"
)


class FixtureSearchProvider:
    def __init__(self, fixture_path: str | Path | None = None) -> None:
        self._path = Path(fixture_path) if fixture_path else DEFAULT_FIXTURE
        self._data = json.loads(self._path.read_text(encoding="utf-8"))
        self.calls: list[SearchRequest] = []

    @property
    def name(self) -> str:
        return "fixture"

    def search(self, request: SearchRequest) -> SearchResponse:
        self.calls.append(request)
        query = request.query.casefold()
        dataset = next(
            (
                value
                for key, value in self._data["datasets"].items()
                if key.casefold() in query
            ),
            None,
        )
        if dataset is None:
            return SearchResponse(
                request=request,
                results=(),
                provider=self.name,
                error_code="FIXTURE_NOT_FOUND",
                error_message=f"No fixture dataset matches query: {request.query}",
            )
        raw_results = dataset.get(request.intent.value, dataset.get("ALL", []))
        results = tuple(
            SearchResult(
                title=item["title"],
                url=item["url"],
                snippet=item.get("snippet", ""),
                rank=index,
                provider=self.name,
                query=request.query,
            )
            for index, item in enumerate(raw_results[: request.limit], start=1)
        )
        return SearchResponse(request, results, self.name)

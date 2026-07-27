"""Offline page fetcher implementing the phase-two fetch contract."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from bs4 import BeautifulSoup

from competitive_intel.domain.urls import normalize_url
from competitive_intel.domain.webpage import (
    FetchPageRequest,
    FetchPageResult,
    FetchStatus,
)


DEFAULT_MANIFEST = (
    Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "sites" / "manifest.json"
)


class FixturePageFetcher:
    def __init__(
        self,
        manifest_path: str | Path | None = None,
        *,
        scenario: str = "unchanged",
    ) -> None:
        path = Path(manifest_path) if manifest_path else DEFAULT_MANIFEST
        manifest = json.loads(path.read_text(encoding="utf-8"))
        self._root = path.parent
        self._pages = {
            normalize_url(url): filename for url, filename in manifest["pages"].items()
        }
        self.calls: list[FetchPageRequest] = []
        self.scenario = scenario

    def fetch(self, request: FetchPageRequest) -> FetchPageResult:
        self.calls.append(request)
        normalized = normalize_url(request.url)
        filename = self._pages.get(normalized)
        now = datetime.now(UTC).replace(tzinfo=None)
        if filename is None:
            return FetchPageResult(
                request.url, normalized, (normalized,), 404, "text/html", None, None,
                now, FetchStatus.FAILED, "FIXTURE_PAGE_NOT_FOUND",
                f"No page fixture for {normalized}",
            )
        if (
            self.scenario == "page_failure"
            and normalized == "https://www.notion.so/pricing"
        ):
            return FetchPageResult(
                request.url, normalized, (normalized,), None, None, None, None,
                now, FetchStatus.FAILED, "FIXTURE_CONNECTION_FAILURE",
                "Fixture pricing-page connection failed.",
            )
        html = (self._root / filename).read_text(encoding="utf-8")
        if (
            self.scenario == "price_changed"
            and normalized == "https://www.notion.so/pricing"
        ):
            html = html.replace(
                "$10 per user / month, billed annually",
                "$12 per user / month, billed annually",
            )
        elif (
            self.scenario == "feature_added"
            and normalized == "https://www.notion.so/product"
        ):
            html = html.replace(
                "</main>",
                "<p>Enterprise Search finds answers across the workspace.</p></main>",
            )
        elif (
            self.scenario == "feature_removed"
            and normalized == "https://www.notion.so/product"
        ):
            html = html.replace(
                "<p>Notion AI helps teams draft and summarize content.</p>",
                "",
            )
        soup = BeautifulSoup(html, "html.parser")
        title = " ".join(soup.title.stripped_strings) if soup.title else None
        return FetchPageResult(
            request.url, normalized, (normalized,), 200, "text/html", title, html,
            now, FetchStatus.SUCCESS,
        )

from __future__ import annotations

from competitive_intel.domain.search import (
    SearchRequest,
    SearchResponse,
    SearchResult,
)
from competitive_intel.domain.sources import (
    DiscoveryStatus,
    SourceDiscoveryLimits,
    SourceType,
    VerificationStatus,
)
from competitive_intel.infrastructure.http.fixture_fetcher import FixturePageFetcher
from competitive_intel.infrastructure.search.providers.fixture import FixtureSearchProvider
from competitive_intel.services.source_discovery_service import SourceDiscoveryService


def test_service_discovers_and_saves_verified_notion_sources(persistence) -> None:
    service = SourceDiscoveryService(
        persistence, FixtureSearchProvider(), FixturePageFetcher()
    )

    result = service.discover("Notion")

    assert result.official_domain == "notion.so"
    assert len(result.saved_source_ids) == 4
    assert {item.source_type for item in result.discoveries} == set(SourceType)
    assert all(
        item.status == DiscoveryStatus.FOUND for item in result.discoveries
    )
    assert any(item.verification_status == VerificationStatus.REJECTED for item in result.validations)
    with persistence.transaction() as session:
        competitor = persistence.competitors.get_by_normalized_name(session, "notion")
        sources = persistence.sources.list_verified(session, competitor["id"])
    assert len(sources) == 4
    assert {item["source_type"] for item in sources} == {
        "HOMEPAGE", "FEATURES", "PRICING", "CHANGELOG"
    }


def test_repeated_discovery_updates_without_duplicate_sources(persistence) -> None:
    service = SourceDiscoveryService(
        persistence, FixtureSearchProvider(), FixturePageFetcher()
    )
    first = service.discover("Notion")
    second = service.discover("Notion")

    assert set(first.saved_source_ids) == set(second.saved_source_ids)
    with persistence.transaction() as session:
        competitor = persistence.competitors.get_by_normalized_name(session, "notion")
        assert len(persistence.sources.list_verified(session, competitor["id"])) == 4


def test_feishu_missing_pricing_and_changelog_remain_not_found(persistence) -> None:
    result = SourceDiscoveryService(
        persistence, FixtureSearchProvider(), FixturePageFetcher()
    ).discover("飞书", language="zh", locale="zh-CN")

    by_type = {item.source_type: item for item in result.discoveries}
    assert result.official_domain == "feishu.cn"
    assert by_type[SourceType.PRICING].status == DiscoveryStatus.NOT_FOUND
    assert by_type[SourceType.CHANGELOG].status == DiscoveryStatus.NOT_FOUND
    assert len(result.saved_source_ids) == 2


def test_validation_limit_stops_additional_candidate_fetches(persistence) -> None:
    fetcher = FixturePageFetcher()
    limits = SourceDiscoveryLimits(max_official_validations=1)
    SourceDiscoveryService(
        persistence, FixtureSearchProvider(), fetcher, limits=limits
    ).discover("Notion")

    # One homepage candidate plus three discovered official pages.
    assert len(fetcher.calls) == 4


class FailingProvider:
    name = "failing"

    def search(self, request: SearchRequest) -> SearchResponse:
        return SearchResponse(
            request, (), self.name, "PROVIDER_UNAVAILABLE", "fixture failure"
        )


def test_provider_failure_is_returned_as_structured_error(persistence) -> None:
    result = SourceDiscoveryService(
        persistence, FailingProvider(), FixturePageFetcher()
    ).discover("Notion")

    assert result.official_domain is None
    assert result.saved_source_ids == ()
    assert any("PROVIDER_UNAVAILABLE" in error for error in result.errors)


class ConflictingProvider:
    name = "conflicting"

    def search(self, request: SearchRequest) -> SearchResponse:
        results = (
            SearchResult("Acme official", "https://acme-one.example/", "official", 1, self.name, request.query),
            SearchResult("Acme official", "https://acme-two.example/", "official", 2, self.name, request.query),
        )
        return SearchResponse(request, results, self.name)


class ConflictingFetcher:
    def fetch(self, request):
        from datetime import UTC, datetime
        from competitive_intel.domain.webpage import FetchPageResult, FetchStatus

        url = request.url
        html = f"""<html><head><title>Acme official</title>
        <link rel='canonical' href='{url}'></head><body><main><h1>Acme</h1>
        <p>Official Acme company workspace.</p><a href='/product'>Product</a>
        <a href='/pricing'>Pricing</a></main><footer>© Acme Corporation</footer></body></html>"""
        return FetchPageResult(
            url, url, (url,), 200, "text/html", "Acme official", html,
            datetime.now(UTC).replace(tzinfo=None), FetchStatus.SUCCESS,
        )


def test_multiple_plausible_official_domains_require_confirmation(persistence) -> None:
    result = SourceDiscoveryService(
        persistence, ConflictingProvider(), ConflictingFetcher()
    ).discover("Acme")

    assert result.official_domain is None
    assert result.saved_source_ids == ()
    assert len(result.pending) == 2
    assert any("Multiple plausible official domains" in item for item in result.warnings)

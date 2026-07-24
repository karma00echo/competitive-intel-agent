from __future__ import annotations

from competitive_intel.domain.content_cleaner import clean_page
from competitive_intel.domain.names import normalize_competitor_name
from competitive_intel.domain.official_validation import validate_official_source
from competitive_intel.domain.search import SearchResult
from competitive_intel.domain.source_discovery import discover_sources
from competitive_intel.domain.sources import (
    DiscoveryStatus,
    PageEvidence,
    SourceType,
    VerificationStatus,
)
from competitive_intel.domain.webpage import CleanPageRequest, FetchPageRequest, FetchStatus
from competitive_intel.infrastructure.http.fixture_fetcher import FixturePageFetcher
from competitive_intel.infrastructure.search.providers.fixture import FixtureSearchProvider


def _evidence(url: str) -> PageEvidence:
    fetched = FixturePageFetcher().fetch(FetchPageRequest(url))
    cleaned = clean_page(CleanPageRequest(fetched.raw_html or "", url))
    return PageEvidence(
        fetched.final_url or url,
        cleaned.page_title,
        cleaned.clean_content,
        fetched.raw_html or "",
        fetched.fetch_status,
    )


def _candidate(title: str, url: str, rank: int = 1) -> SearchResult:
    return SearchResult(title, url, "candidate", rank, "fixture", "query")


def test_official_homepage_is_verified_by_multiple_independent_signals() -> None:
    result = validate_official_source(
        normalize_competitor_name("Notion"),
        _candidate("Notion", "https://www.notion.so/"),
        _evidence("https://www.notion.so/"),
    )
    assert result.verification_status == VerificationStatus.VERIFIED
    assert "brand_matches_domain" in result.supporting_signals
    assert "same_domain_canonical" in result.supporting_signals
    assert result.confidence >= 0.63


def test_third_party_categories_are_rejected_without_fetching() -> None:
    identity = normalize_competitor_name("Notion")
    urls = (
        "https://en.wikipedia.org/wiki/Notion",
        "https://techcrunch.com/notion-news",
        "https://apps.apple.com/app/notion/id1",
        "https://softonic.com/notion",
    )
    assert all(
        validate_official_source(identity, _candidate("Notion", url))
        .verification_status
        == VerificationStatus.REJECTED
        for url in urls
    )


def test_failed_or_javascript_shell_page_cannot_be_verified() -> None:
    identity = normalize_competitor_name("Notion")
    candidate = _candidate("Notion", "https://notion.so/")
    for status in (FetchStatus.FAILED, FetchStatus.JS_UNSUPPORTED):
        evidence = PageEvidence("https://notion.so/", "Notion", "", "", status)
        result = validate_official_source(identity, candidate, evidence)
        assert result.verification_status == VerificationStatus.PENDING_CONFIRMATION


def test_strong_page_evidence_can_verify_nonmatching_corporate_domain() -> None:
    html = """
    <html><head><title>Acme Cloud</title>
    <link rel="canonical" href="https://workspace.example/"></head>
    <body><main><h1>Acme Cloud</h1><p>Official Acme Cloud workspace.</p>
    <a href="/product">Product</a><a href="/pricing">Pricing</a></main>
    <footer>© Acme Cloud Corporation</footer></body></html>
    """
    cleaned = clean_page(CleanPageRequest(html, "https://workspace.example/"))
    evidence = PageEvidence(
        "https://workspace.example/", cleaned.page_title, cleaned.clean_content,
        html, FetchStatus.SUCCESS,
    )
    result = validate_official_source(
        normalize_competitor_name("Acme Cloud"),
        _candidate("Acme Cloud official", "https://workspace.example/"),
        evidence,
    )
    assert result.verification_status == VerificationStatus.VERIFIED
    assert "brand_copyright" in result.supporting_signals


def test_homepage_discovers_features_pricing_and_changelog() -> None:
    fetched = FixturePageFetcher().fetch(FetchPageRequest("https://www.notion.so/"))
    results = discover_sources(
        normalize_competitor_name("Notion"),
        "https://www.notion.so/",
        fetched.raw_html or "",
        tuple(SourceType),
        provider=FixtureSearchProvider(),
    )
    by_type = {item.source_type: item for item in results}
    assert by_type[SourceType.HOMEPAGE].status == DiscoveryStatus.FOUND
    assert by_type[SourceType.FEATURES].candidate_url == "https://www.notion.so/product"
    assert by_type[SourceType.PRICING].candidate_url == "https://www.notion.so/pricing"
    assert by_type[SourceType.CHANGELOG].candidate_url == "https://www.notion.so/releases"


def test_missing_public_pricing_and_changelog_are_not_fabricated() -> None:
    fetched = FixturePageFetcher().fetch(FetchPageRequest("https://www.feishu.cn/"))
    results = discover_sources(
        normalize_competitor_name("飞书"),
        "https://www.feishu.cn/",
        fetched.raw_html or "",
        tuple(SourceType),
        provider=FixtureSearchProvider(),
        language="zh",
    )
    by_type = {item.source_type: item for item in results}
    assert by_type[SourceType.FEATURES].status == DiscoveryStatus.FOUND
    assert by_type[SourceType.PRICING].status == DiscoveryStatus.NOT_FOUND
    assert by_type[SourceType.CHANGELOG].status == DiscoveryStatus.NOT_FOUND
    assert all(
        not item.candidate_url or "contact" not in item.candidate_url
        for item in results
    )


def test_empty_homepage_is_explicitly_unsupported() -> None:
    results = discover_sources(
        normalize_competitor_name("Notion"),
        "https://www.notion.so/",
        "",
        tuple(SourceType),
        provider=FixtureSearchProvider(),
    )
    assert all(item.status == DiscoveryStatus.UNSUPPORTED for item in results)


def test_supplemental_search_limit_stops_additional_queries() -> None:
    provider = FixtureSearchProvider()
    results = discover_sources(
        normalize_competitor_name("飞书"),
        "https://www.feishu.cn/",
        "<html><body><main><h1>飞书</h1></main></body></html>",
        (SourceType.PRICING, SourceType.CHANGELOG),
        provider=provider,
        language="zh",
        max_supplemental_searches=1,
    )
    assert len(provider.calls) == 1
    assert all(item.status == DiscoveryStatus.NOT_FOUND for item in results)

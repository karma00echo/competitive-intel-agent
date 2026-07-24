from __future__ import annotations

from competitive_intel.domain.names import normalize_competitor_name
from competitive_intel.domain.query_generator import generate_search_queries
from competitive_intel.domain.search import SearchIntent, SearchRequest
from competitive_intel.domain.urls import normalize_url
from competitive_intel.infrastructure.search.providers.fixture import (
    FixtureSearchProvider,
)
from competitive_intel.infrastructure.search.search_web import search_web


def test_fixture_search_provider_returns_mixed_ranked_results() -> None:
    provider = FixtureSearchProvider()
    response = search_web(
        provider,
        SearchRequest("Notion official website", SearchIntent.OFFICIAL_SITE, limit=10)
    )

    assert response.ok
    assert response.provider == "fixture"
    assert len(response.results) == 6
    assert response.results[0].rank == 1
    assert any("wikipedia.org" in item.url for item in response.results)
    assert all(item.query == "Notion official website" for item in response.results)


def test_missing_fixture_returns_structured_error() -> None:
    response = FixtureSearchProvider().search(
        SearchRequest("UnknownCo official", SearchIntent.OFFICIAL_SITE)
    )

    assert not response.ok
    assert response.error_code == "FIXTURE_NOT_FOUND"
    assert response.results == ()


def test_query_generation_supports_english_chinese_dedup_and_limits() -> None:
    notion = normalize_competitor_name("Notion")
    feishu = normalize_competitor_name(" 飞书 ")

    english = generate_search_queries(
        notion, SearchIntent.CHANGELOG, max_queries=2
    )
    chinese = generate_search_queries(
        feishu, SearchIntent.PRICING, language="zh", max_queries=2
    )

    assert english == ("Notion changelog", "Notion release notes")
    assert chinese == ("飞书 定价", "飞书 价格 套餐")
    assert len(english) == len(set(english)) == 2
    assert feishu.original_name == "飞书"
    assert notion.normalized_name == "notion"


def test_site_limited_queries_use_confirmed_domain() -> None:
    queries = generate_search_queries(
        normalize_competitor_name("Notion"),
        SearchIntent.PRICING,
        official_domain="notion.so",
        max_queries=2,
    )
    assert queries == ("site:notion.so pricing", "site:notion.so plans")


def test_url_normalization_removes_tracking_and_fragment_but_keeps_business_query() -> None:
    value = normalize_url(
        "HTTPS://Exämple.COM:443/pricing/?utm_source=x&plan=team&gclid=1#top"
    )
    assert value == "https://xn--exmple-cua.com/pricing?plan=team"


def test_relative_url_and_equivalent_trailing_slash_normalize_identically() -> None:
    relative = normalize_url("../pricing/", base_url="https://Example.com/product/")
    absolute = normalize_url("https://example.com/pricing")
    assert relative == absolute == "https://example.com/pricing"

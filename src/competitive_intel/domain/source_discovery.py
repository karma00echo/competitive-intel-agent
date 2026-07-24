"""Discover official page candidates from a verified homepage."""

from __future__ import annotations

from collections import defaultdict

from bs4 import BeautifulSoup

from competitive_intel.infrastructure.search.base import SearchProvider

from .query_generator import generate_search_queries
from .search import SearchIntent, SearchRequest
from .sources import (
    CompetitorIdentity, DiscoveredSource, DiscoveryStatus, SourceType,
)
from .urls import normalize_url, same_site


KEYWORDS = {
    SourceType.FEATURES: ("features", "product", "solutions", "功能", "产品", "解决方案"),
    SourceType.PRICING: ("pricing", "plans", "price", "定价", "价格", "套餐", "版本"),
    SourceType.CHANGELOG: ("changelog", "release notes", "updates", "what's new", "更新", "更新日志", "发布记录", "新功能"),
}
INTENTS = {
    SourceType.FEATURES: SearchIntent.FEATURES,
    SourceType.PRICING: SearchIntent.PRICING,
    SourceType.CHANGELOG: SearchIntent.CHANGELOG,
}


def discover_sources(
    identity: CompetitorIdentity,
    verified_homepage: str,
    homepage_html: str,
    required_types: tuple[SourceType, ...],
    *,
    provider: SearchProvider,
    locale: str = "en-US",
    language: str = "en",
    max_pages: int = 8,
    max_internal_links: int = 100,
    max_supplemental_searches: int = 3,
) -> tuple[DiscoveredSource, ...]:
    if not homepage_html.strip():
        return tuple(
            DiscoveredSource(
                source_type, None, None, "homepage_unavailable", (), 0.0,
                False, DiscoveryStatus.UNSUPPORTED,
            )
            for source_type in required_types
        )
    soup = BeautifulSoup(homepage_html, "html.parser")
    scored: dict[SourceType, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for anchor in soup.find_all("a", href=True)[:max_internal_links]:
        try:
            url = normalize_url(str(anchor["href"]), base_url=verified_homepage)
        except ValueError:
            continue
        if not same_site(url, verified_homepage):
            continue
        haystack = f"{anchor.get_text(' ', strip=True)} {url}".casefold()
        for source_type, keywords in KEYWORDS.items():
            matches = {word for word in keywords if word in haystack}
            if matches:
                scored[source_type][url].update(matches)

    supplemental = 0
    output: list[DiscoveredSource] = []
    for source_type in required_types:
        if source_type == SourceType.HOMEPAGE:
            output.append(DiscoveredSource(
                source_type, verified_homepage, normalize_url(verified_homepage),
                "verified_homepage", ("verified_official_domain",), 1.0, False,
                DiscoveryStatus.FOUND,
            ))
            continue
        candidates = scored.get(source_type, {})
        if not candidates and supplemental < max_supplemental_searches:
            query = generate_search_queries(
                identity, INTENTS[source_type], official_domain=domain_from_homepage(verified_homepage),
                language=language, max_queries=1,
            )[0]
            response = provider.search(SearchRequest(query, INTENTS[source_type], locale, language, 5))
            supplemental += 1
            if response.ok:
                for result in response.results:
                    try:
                        url = normalize_url(result.url)
                    except ValueError:
                        continue
                    if same_site(url, verified_homepage):
                        haystack = f"{result.title} {result.snippet} {url}".casefold()
                        matches = {word for word in KEYWORDS[source_type] if word in haystack}
                        if matches:
                            candidates[url].update(matches)
        if not candidates:
            output.append(DiscoveredSource(
                source_type, None, None, "navigation_and_site_search", (), 0.0,
                False, DiscoveryStatus.NOT_FOUND,
            ))
            continue
        ranked = sorted(candidates.items(), key=lambda item: (-len(item[1]), item[0]))
        url, signals = ranked[0]
        status = DiscoveryStatus.AMBIGUOUS if len(ranked) > 1 and len(ranked[0][1]) == len(ranked[1][1]) else DiscoveryStatus.FOUND
        output.append(DiscoveredSource(
            source_type, url, url, "internal_link_or_site_search",
            tuple(sorted(signals)), min(0.95, 0.55 + 0.1 * len(signals)), True, status,
        ))
        if len(output) >= max_pages:
            break
    return tuple(output)


def domain_from_homepage(url: str) -> str:
    from .urls import domain_from_url
    return domain_from_url(url)

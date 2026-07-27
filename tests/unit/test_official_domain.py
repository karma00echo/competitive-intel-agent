from __future__ import annotations

import inspect

from competitive_intel.domain.names import normalize_competitor_name
from competitive_intel.domain.official_domain import (
    aggregate_domain_evidence,
    select_official_domain,
)
from competitive_intel.domain.search import SearchResult
from competitive_intel.domain.sources import (
    OfficialSourceValidation,
    PageEvidence,
    SourceType,
    VerificationStatus,
)
from competitive_intel.domain.urls import registrable_domain
from competitive_intel.domain.webpage import FetchStatus


def _result(url: str, query: str, *, title: str = "Acme official") -> SearchResult:
    return SearchResult(title, url, "Official Acme product", 1, "fixture", query)


def _page(
    url: str,
    *,
    final_url: str | None = None,
    title: str = "Acme",
    canonical: str | None = None,
) -> PageEvidence:
    canonical = canonical or final_url or url
    html = (
        f"<html><head><title>{title}</title>"
        f"<link rel='canonical' href='{canonical}'>"
        "<meta property='og:site_name' content='Acme'></head>"
        "<body><main><h1>Acme product</h1></main></body></html>"
    )
    return PageEvidence(
        final_url or url, title, "Acme product", html, FetchStatus.SUCCESS
    )


def _validation(url: str) -> OfficialSourceValidation:
    return OfficialSourceValidation(
        url, url, registrable_domain(url), VerificationStatus.PENDING_CONFIRMATION,
        SourceType.HOMEPAGE, 0.5, (), (), "pending",
    )


def _complete_domain(domain: str) -> tuple[SearchResult, ...]:
    return (
        _result(f"https://www.{domain}/", "Acme official homepage"),
        _result(f"https://www.{domain}/pricing", "Acme pricing"),
        _result(f"https://product.{domain}/features", "Acme product features"),
        _result(f"https://www.{domain}/releases", "Acme changelog releases"),
    )


def test_psl_groups_subdomains_and_handles_multilabel_suffixes() -> None:
    assert registrable_domain("https://help.example.com/x") == "example.com"
    assert registrable_domain("https://app.example.co.uk") == "example.co.uk"
    assert registrable_domain("https://www.example.com.cn") == "example.com.cn"


def test_cross_query_evidence_with_clear_margin_is_verified() -> None:
    official = _complete_domain("acme.com")
    third_party = (_result("https://www.g2.com/products/acme", "Acme official"),)
    representative = official[0]
    evidence = aggregate_domain_evidence(
        normalize_competitor_name("Acme"),
        official + third_party,
        (_validation(representative.url), _validation(third_party[0].url)),
        {representative.url: _page(representative.url)},
    )

    selected, reason = select_official_domain(evidence)

    assert selected == "acme.com"
    assert evidence[0].query_type_coverage == (
        "changelog", "features", "homepage", "pricing"
    )
    assert "Auto-verified" in reason
    rejected = next(item for item in evidence if item.registrable_domain == "g2.com")
    assert rejected.rejection_reasons


def test_first_rank_third_party_does_not_override_official_evidence() -> None:
    third_party = _result(
        "https://www.g2.com/products/acme", "Acme official", title="Acme reviews"
    )
    official = _complete_domain("acme.com")
    representative = official[0]
    evidence = aggregate_domain_evidence(
        normalize_competitor_name("Acme"),
        (third_party,) + official,
        (_validation(third_party.url), _validation(representative.url)),
        {representative.url: _page(representative.url)},
    )

    selected, _ = select_official_domain(evidence)

    assert selected == "acme.com"
    assert next(
        item for item in evidence if item.registrable_domain == "g2.com"
    ).score == 0


def test_two_close_domains_remain_pending() -> None:
    first = _complete_domain("acme-one.com")
    second = _complete_domain("acme-two.com")
    pages = {
        first[0].url: _page(first[0].url),
        second[0].url: _page(second[0].url),
    }
    evidence = aggregate_domain_evidence(
        normalize_competitor_name("Acme"),
        first + second,
        (_validation(first[0].url), _validation(second[0].url)),
        pages,
    )

    selected, reason = select_official_domain(evidence)

    assert selected is None
    assert "close scores" in reason


def test_redirect_and_canonical_support_are_audited() -> None:
    candidates = _complete_domain("acme.com")
    first = candidates[0]
    evidence = aggregate_domain_evidence(
        normalize_competitor_name("Acme"),
        candidates,
        (_validation(first.url),),
        {
            first.url: _page(
                first.url,
                final_url="https://app.acme.com/",
                canonical="https://www.acme.com/",
            )
        },
    )[0]

    assert evidence.redirect_support == 1
    assert evidence.page_metadata_support == 3


def test_title_brand_mismatch_reduces_metadata_support() -> None:
    candidates = _complete_domain("acme.com")
    first = candidates[0]
    evidence = aggregate_domain_evidence(
        normalize_competitor_name("Acme"),
        candidates,
        (_validation(first.url),),
        {first.url: _page(first.url, title="Unrelated portal")},
    )[0]

    assert evidence.page_metadata_support == 2


def test_disambiguation_contains_no_competitor_specific_domain_hardcoding() -> None:
    import competitive_intel.domain.official_domain as module

    source = inspect.getsource(module).casefold()
    assert "linear" not in source
    assert "asana" not in source

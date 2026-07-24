"""Evidence-based official-source validation without search-rank trust."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .search import SearchResult
from .sources import (
    CompetitorIdentity,
    OfficialSourceValidation,
    PageEvidence,
    SourceType,
    VerificationStatus,
)
from .urls import domain_from_url, normalize_url, same_site
from .webpage import FetchStatus


REJECTED_DOMAINS = {
    "wikipedia.org", "wikidata.org", "linkedin.com", "facebook.com",
    "twitter.com", "x.com", "youtube.com", "apps.apple.com",
    "play.google.com", "softonic.com", "cnet.com", "techcrunch.com",
    "crunchbase.com", "g2.com", "getapp.com", "googleadservices.com",
    "baike.baidu.com",
}


def _rejected_domain(domain: str) -> str | None:
    return next(
        (item for item in REJECTED_DOMAINS if domain == item or domain.endswith(f".{item}")),
        None,
    )


def _brand_terms(identity: CompetitorIdentity) -> tuple[str, ...]:
    values = (identity.original_name, identity.normalized_name, *identity.aliases)
    return tuple(
        dict.fromkeys(
            re.sub(r"[^\w\u4e00-\u9fff]", "", value.casefold())
            for value in values if value
        )
    )


def validate_official_source(
    identity: CompetitorIdentity,
    candidate: SearchResult,
    page: PageEvidence | None = None,
    *,
    source_type: SourceType = SourceType.HOMEPAGE,
) -> OfficialSourceValidation:
    normalized = normalize_url(page.final_url if page else candidate.url)
    domain = domain_from_url(normalized)
    risk: list[str] = []
    support: list[str] = []
    rejected = _rejected_domain(domain)
    if rejected:
        risk.append(f"third_party_domain:{rejected}")
        return OfficialSourceValidation(
            candidate.url, normalized, domain, VerificationStatus.REJECTED,
            source_type, 0.99, (), tuple(risk),
            "Candidate is a known third-party, media, social, store, or aggregator domain.",
        )
    if page is None or page.fetch_status != FetchStatus.SUCCESS or not page.clean_content:
        risk.append("page_evidence_unavailable")
        return OfficialSourceValidation(
            candidate.url, normalized, domain, VerificationStatus.PENDING_CONFIRMATION,
            source_type, 0.25, (), tuple(risk),
            "A successful non-empty page is required before official verification.",
        )

    terms = _brand_terms(identity)
    compact_domain = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", domain.casefold())
    title = (page.page_title or "").casefold()
    content = page.clean_content.casefold()
    raw = page.raw_html.casefold()
    if any(term and term in compact_domain for term in terms):
        support.append("brand_matches_domain")
    if any(term and term in re.sub(r"\W", "", title) for term in terms):
        support.append("brand_in_page_title")
    if any(term and term in re.sub(r"\W", "", content) for term in terms):
        support.append("brand_in_page_content")
    soup = BeautifulSoup(page.raw_html, "html.parser")
    canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
    if canonical and canonical.get("href"):
        try:
            if same_site(normalized, str(canonical["href"])):
                support.append("same_domain_canonical")
        except ValueError:
            risk.append("invalid_canonical")
    links = [a.get("href") for a in soup.find_all("a", href=True)]
    internal = 0
    for href in links[:100]:
        try:
            if same_site(normalized, normalize_url(str(href), base_url=normalized)):
                internal += 1
        except ValueError:
            continue
    if internal >= 2:
        support.append("multiple_internal_links")
    if "copyright" in raw or "©" in page.raw_html:
        if any(term and term in re.sub(r"\W", "", raw) for term in terms):
            support.append("brand_copyright")

    rank_signal = max(0, 11 - min(candidate.rank, 10)) * 0.001
    score = min(0.98, 0.15 + 0.16 * len(set(support)) + rank_signal)
    strong = len(set(support)) >= 3 and (
        "brand_matches_domain" in support
        or "brand_copyright" in support
        or ("brand_in_page_title" in support and "same_domain_canonical" in support)
    )
    status = VerificationStatus.VERIFIED if strong and score >= 0.63 else VerificationStatus.PENDING_CONFIRMATION
    reason = (
        "Multiple independent brand, domain, canonical, and site signals support official ownership."
        if status == VerificationStatus.VERIFIED
        else "Evidence is plausible but insufficient to confirm a unique official domain."
    )
    return OfficialSourceValidation(
        candidate.url, normalized, domain, status, source_type, round(score, 4),
        tuple(dict.fromkeys(support)), tuple(risk), reason,
    )

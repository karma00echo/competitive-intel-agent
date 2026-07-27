"""Deterministic, auditable aggregation of official-domain evidence."""

from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from bs4 import BeautifulSoup

from .names import normalize_competitor_name
from .official_validation import _rejected_domain
from .search import SearchResult
from .sources import CompetitorIdentity, OfficialSourceValidation, PageEvidence
from .urls import normalize_url, registrable_domain
from .webpage import FetchStatus


AUTO_VERIFY_SCORE = 8.0
AUTO_VERIFY_MARGIN = 2.0


@dataclass(frozen=True, slots=True)
class OfficialDomainEvidence:
    registrable_domain: str
    score: float
    supporting_result_count: int
    query_type_coverage: tuple[str, ...]
    brand_match_count: int
    redirect_support: int
    page_metadata_support: int
    homepage_support: bool
    rejection_reasons: tuple[str, ...]
    supporting_urls: tuple[str, ...]

    def audit_summary(self) -> str:
        coverage = ",".join(self.query_type_coverage) or "none"
        rejected = ",".join(self.rejection_reasons) or "none"
        return (
            f"domain={self.registrable_domain}; score={self.score:.1f}; "
            f"results={self.supporting_result_count}; coverage={coverage}; "
            f"brand={self.brand_match_count}; redirect={self.redirect_support}; "
            f"metadata={self.page_metadata_support}; homepage={self.homepage_support}; "
            f"rejections={rejected}"
        )[:500]


def _brand_terms(identity: CompetitorIdentity) -> tuple[str, ...]:
    values = (identity.original_name, identity.normalized_name, *identity.aliases)
    return tuple(
        dict.fromkeys(
            re.sub(r"[^\w\u4e00-\u9fff]", "", value.casefold())
            for value in values if value
        )
    )


def _matches_brand(text: str, terms: tuple[str, ...]) -> bool:
    compact = re.sub(r"[^\w\u4e00-\u9fff]", "", text.casefold())
    return any(term and term in compact for term in terms)


def _query_type(result: SearchResult) -> str:
    value = f"{result.query} {result.title} {result.url}".casefold()
    if any(word in value for word in ("pricing", "plans", "价格", "定价")):
        return "pricing"
    if any(word in value for word in ("changelog", "release", "updates", "更新")):
        return "changelog"
    if any(word in value for word in ("features", "product", "功能", "产品")):
        return "features"
    return "homepage"


def _is_homepage(url: str) -> bool:
    path = urlsplit(normalize_url(url)).path.rstrip("/")
    return not path or path.casefold() in {"/home", "/en", "/zh", "/zh-cn"}


def aggregate_domain_evidence(
    identity: CompetitorIdentity,
    candidates: tuple[SearchResult, ...],
    validations: tuple[OfficialSourceValidation, ...],
    pages: dict[str, PageEvidence],
) -> tuple[OfficialDomainEvidence, ...]:
    """Aggregate independent search and page signals by PSL registrable domain."""
    terms = _brand_terms(identity)
    by_domain: dict[str, list[SearchResult]] = {}
    for candidate in candidates:
        try:
            domain = registrable_domain(candidate.url)
        except ValueError:
            continue
        by_domain.setdefault(domain, []).append(candidate)

    validation_by_url = {normalize_url(item.candidate_url): item for item in validations}
    evidence: list[OfficialDomainEvidence] = []
    for domain, results in by_domain.items():
        urls = tuple(dict.fromkeys(normalize_url(item.url) for item in results))
        coverage = tuple(sorted({_query_type(item) for item in results}))
        brand_matches = sum(
            _matches_brand(f"{item.title} {item.snippet}", terms) for item in results
        )
        rejections = tuple(
            sorted({
                reason
                for url in urls
                for reason in (
                    validation_by_url[url].risk_signals
                    if url in validation_by_url else ()
                )
                if reason.startswith("third_party_domain:")
            })
        )
        if _rejected_domain(domain):
            rejections = tuple(sorted({*rejections, f"third_party_domain:{domain}"}))

        redirect_support = 0
        metadata_support = 0
        homepage_support = any(_is_homepage(url) for url in urls)
        subdomains: set[str] = set()
        for url in urls:
            subdomains.add(urlsplit(url).hostname or "")
            page = pages.get(url)
            if page is None or page.fetch_status != FetchStatus.SUCCESS:
                continue
            final_domain = registrable_domain(page.final_url)
            if final_domain == domain:
                redirect_support += 1
            soup = BeautifulSoup(page.raw_html, "html.parser")
            if _matches_brand(page.page_title or "", terms):
                metadata_support += 1
            canonical = soup.find("link", rel=lambda value: value and "canonical" in value)
            if canonical and canonical.get("href"):
                try:
                    if registrable_domain(str(canonical["href"])) == domain:
                        metadata_support += 1
                except ValueError:
                    pass
            og_site = soup.find("meta", attrs={"property": "og:site_name"})
            if og_site and _matches_brand(str(og_site.get("content", "")), terms):
                metadata_support += 1

        typical_paths = sum(
            any(token in urlsplit(url).path.casefold() for token in (
                "pricing", "plans", "product", "features", "changelog", "release",
            ))
            for url in urls
        )
        score = (
            min(len(results), 3) * 0.5
            + len(coverage) * 0.75
            + min(brand_matches, 4) * 0.75
            + (2.0 if homepage_support else 0.0)
            + min(redirect_support, 1) * 1.0
            + min(metadata_support, 3) * 0.75
            + min(typical_paths, 3) * 0.25
            + (0.5 if len(subdomains) > 1 else 0.0)
        )
        if rejections:
            score = 0.0
        evidence.append(OfficialDomainEvidence(
            domain, round(score, 2), len(results), coverage, brand_matches,
            redirect_support, metadata_support, homepage_support, rejections, urls[:8],
        ))
    return tuple(sorted(evidence, key=lambda item: (-item.score, item.registrable_domain)))


def select_official_domain(
    evidence: tuple[OfficialDomainEvidence, ...],
) -> tuple[str | None, str]:
    eligible = [item for item in evidence if not item.rejection_reasons]
    if not eligible:
        return None, "No candidate passed hard rejection rules."
    top = eligible[0]
    runner_up = eligible[1] if len(eligible) > 1 else None
    margin = top.score - runner_up.score if runner_up else top.score
    sufficient_brand = top.brand_match_count >= 1 and top.page_metadata_support >= 1
    if (
        top.score >= AUTO_VERIFY_SCORE
        and margin >= AUTO_VERIFY_MARGIN
        and sufficient_brand
        and top.homepage_support
    ):
        return top.registrable_domain, (
            f"Auto-verified: {top.audit_summary()}; margin={margin:.1f}"
        )[:600]
    ambiguity = (
        " Multiple plausible official domains have close scores."
        if runner_up and margin < AUTO_VERIFY_MARGIN else ""
    )
    return None, (
        f"Pending confirmation:{ambiguity} {top.audit_summary()}; margin={margin:.1f}; "
        f"threshold={AUTO_VERIFY_SCORE:.1f}; required_margin={AUTO_VERIFY_MARGIN:.1f}"
    )[:600]

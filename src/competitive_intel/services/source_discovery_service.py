"""Bounded deterministic competitor source-discovery orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import urlsplit

from competitive_intel.domain.content_cleaner import clean_page
from competitive_intel.domain.names import normalize_competitor_name
from competitive_intel.domain.official_domain import (
    aggregate_domain_evidence,
    select_official_domain,
)
from competitive_intel.domain.official_validation import validate_official_source
from competitive_intel.domain.query_generator import generate_search_queries
from competitive_intel.domain.search import SearchIntent, SearchRequest, SearchResult
from competitive_intel.domain.source_discovery import discover_sources, applicable_page
from competitive_intel.domain.sources import (
    DiscoveryStatus,
    OfficialSourceValidation,
    PageEvidence,
    SourceDiscoveryLimits,
    SourceDiscoveryResult,
    SourceType,
    VerificationStatus,
)
from competitive_intel.domain.urls import normalize_url, registrable_domain
from competitive_intel.domain.webpage import (
    CleanPageRequest,
    FetchPageRequest,
    FetchStatus,
)
from competitive_intel.infrastructure.search.base import SearchProvider
from competitive_intel.infrastructure.search.search_web import search_web
from competitive_intel.persistence import Persistence


def identity_candidate_key(candidate: SearchResult, identity):
    """Prefer a brand-labelled about page over a root that may be an app shell.

    This changes only which page gets fetched, never the ownership threshold.
    """
    url = normalize_url(candidate.url)
    segments = urlsplit(url).path.strip('/').casefold().split('/')
    about = segments[-1] in {'about', 'about-us', 'company'}
    branded = any(name.casefold() in candidate.title.casefold()
                  for name in (identity.original_name, identity.normalized_name, *identity.aliases) if name)
    return (0 if about and branded else 1, len(url.split('/', 3)[-1]), candidate.rank, url)


class SourceDiscoveryService:
    def __init__(
        self,
        persistence: Persistence,
        search_provider: SearchProvider,
        page_fetcher,
        *,
        limits: SourceDiscoveryLimits | None = None,
    ) -> None:
        self._persistence = persistence
        self._search = search_provider
        self._fetcher = page_fetcher
        self._limits = limits or SourceDiscoveryLimits()
        self.fetch_audit = []
        self.search_audit = []

    def discover(
        self,
        competitor_name: str,
        *,
        aliases: tuple[str, ...] = (),
        locale: str = "en-US",
        language: str | None = None,
        search_intents: tuple[SearchIntent, ...] | None = None,
        expected_domain: str | None = None,
    ) -> SourceDiscoveryResult:
        identity = normalize_competitor_name(competitor_name, aliases)
        self.fetch_audit = []
        self.search_audit = []
        lang = language or (
            "zh" if any("\u4e00" <= c <= "\u9fff" for c in competitor_name) else "en"
        )
        search_plan = tuple(
            (
                intent,
                generate_search_queries(
                    identity, intent, language=lang, max_queries=1
                )[0],
            )
            for intent in (search_intents or (
                SearchIntent.OFFICIAL_SITE,
                SearchIntent.FEATURES,
                SearchIntent.PRICING,
                SearchIntent.CHANGELOG,
            ))
        )
        queries = tuple(query for _, query in search_plan)
        errors: list[str] = []
        warnings: list[str] = []
        candidates_by_url: dict[str, SearchResult] = {}
        executed: set[str] = set()
        for intent, query in search_plan:
            if query in executed:
                continue
            executed.add(query)
            response = search_web(
                self._search,
                SearchRequest(
                    query,
                    intent,
                    locale,
                    lang,
                    self._limits.max_results_per_query,
                ),
            )
            self.search_audit.append({"query": query, "locale": locale, "language": lang,
                                      "ok": response.ok, "result_count": len(response.results),
                                      "error_code": response.error_code})
            if not response.ok:
                errors.append(f"{response.error_code}: {response.error_message}")
                continue
            for result in response.results:
                try:
                    normalized = normalize_url(result.url)
                except ValueError as exc:
                    warnings.append(f"Invalid candidate URL {result.url}: {exc}")
                    continue
                candidates_by_url.setdefault(normalized, result)
                if len(candidates_by_url) >= self._limits.max_candidate_urls:
                    warnings.append("Candidate URL limit reached.")
                    break

        validations: list[OfficialSourceValidation] = []
        page_cache: dict[str, PageEvidence] = {}
        candidate_groups: dict[str, list[SearchResult]] = {}
        for result in candidates_by_url.values():
            preliminary = validate_official_source(identity, result)
            if preliminary.verification_status == VerificationStatus.REJECTED:
                validations.append(preliminary)
                continue
            candidate_groups.setdefault(registrable_domain(result.url), []).append(result)

        representatives = [
            min(
                items,
                key=lambda item: identity_candidate_key(item, identity),
            )
            for _, items in sorted(
                candidate_groups.items(),
                key=lambda item: (
                    -sum(
                        identity.normalized_name.casefold()
                        in f"{result.title} {result.snippet}".casefold()
                        for result in item[1]
                    ),
                    -len(item[1]),
                    item[0],
                ),
            )[: self._limits.max_official_validations]
        ]
        for representative in representatives:
            group = candidate_groups[registrable_domain(representative.url)]
            for result in sorted(group, key=lambda item: identity_candidate_key(item, identity))[:self._limits.max_identity_pages_per_domain]:
                page = self._fetch_evidence(result.url)
                if page is not None:
                    page_cache[normalize_url(result.url)] = page
                    page_cache[normalize_url(page.final_url)] = page
                validation = validate_official_source(identity, result, page)
                validations.append(validation)
                if page and page.fetch_status == FetchStatus.SUCCESS and page.clean_content.strip():
                    break
                if page and page.fetch_status == FetchStatus.BLOCKED:
                    break
        if len(candidate_groups) > self._limits.max_official_validations:
            warnings.append("Official domain validation limit reached.")

        domain_evidence = aggregate_domain_evidence(
            identity, tuple(candidates_by_url.values()), tuple(validations), page_cache
        )
        selected_domain, decision_reason = select_official_domain(domain_evidence)
        if expected_domain and selected_domain != expected_domain:
            selected_domain = None
            decision_reason = "Discovery/research identity mismatch; no profile or sources updated."
        official = None
        if selected_domain:
            matching = [
                item for item in validations
                if registrable_domain(item.normalized_url) == selected_domain
                and item.verification_status != VerificationStatus.REJECTED
            ]
            if matching:
                selected = max(matching, key=lambda item: item.confidence)
                official = replace(
                    selected,
                    domain=selected_domain,
                    verification_status=VerificationStatus.VERIFIED,
                    confidence=min(0.99, max(selected.confidence, 0.8)),
                    verification_reason=decision_reason,
                )
                validations[validations.index(selected)] = official
        else:
            warnings.append(decision_reason)
            validations = [
                replace(
                    item,
                    verification_status=VerificationStatus.PENDING_CONFIRMATION,
                    verification_reason=decision_reason,
                )
                if item.verification_status == VerificationStatus.VERIFIED else item
                for item in validations
            ]
        discoveries = ()
        saved_ids: list[int] = []
        if official:
            homepage_page = page_cache.get(official.normalized_url)
            if homepage_page is None:
                errors.append("Verified homepage evidence was not retained.")
            else:
                discoveries = discover_sources(
                    identity,
                    official.normalized_url,
                    homepage_page.raw_html,
                    (
                        SourceType.HOMEPAGE,
                        SourceType.FEATURES,
                        SourceType.PRICING,
                        SourceType.CHANGELOG,
                    ),
                    provider=self._search,
                    locale=locale,
                    language=lang,
                    max_pages=self._limits.max_pages,
                    max_internal_links=self._limits.max_internal_links,
                    max_supplemental_searches=self._limits.max_supplemental_searches,
                    existing_results=tuple(candidates_by_url.values()),
                    max_candidates_per_type=self._limits.max_candidates_per_type,
                )
                validated_discoveries = []
                for discovery in discoveries:
                    if not discovery.candidate_url:
                        validated_discoveries.append(discovery)
                        continue
                    if discovery.source_type == SourceType.HOMEPAGE:
                        saved_ids.append(self._save_verified(identity, official))
                        validated_discoveries.append(replace(discovery, needs_validation=False))
                        continue
                    options = discovery.candidate_urls or (discovery.candidate_url,)
                    scores = discovery.candidate_scores or (1,) * len(options)
                    accepted = []
                    for index, url in enumerate(options[:self._limits.max_candidates_per_type]):
                        if accepted and scores[index] < accepted[0][0]:
                            break
                        page = page_cache.get(normalize_url(url))
                        if page is None:
                            page = self._fetch_evidence(url)
                            page_cache[normalize_url(url)] = page
                        synthetic = SearchResult(discovery.source_type.value, url,
                            "Candidate from official navigation or search; not evidence.", 1,
                            self._search.name, "internal discovery")
                        validation = validate_official_source(identity, synthetic, page, source_type=discovery.source_type)
                        validations.append(validation)
                        owned = registrable_domain(validation.normalized_url) == official.domain
                        suitable = owned and applicable_page(discovery.source_type, page)
                        self.fetch_audit.append({"url": url, "source_type": discovery.source_type.value,
                                                 "candidate_applicable": suitable, "ownership_matches": owned})
                        if validation.verification_status == VerificationStatus.VERIFIED and suitable:
                            accepted.append((scores[index], validation))
                        if page and page.fetch_status == FetchStatus.BLOCKED:
                            break
                    if len(accepted) == 1:
                        validation = accepted[0][1]
                        saved_ids.append(self._save_verified(identity, validation))
                        validated_discoveries.append(replace(discovery, candidate_url=validation.candidate_url,
                            normalized_url=validation.normalized_url, status=DiscoveryStatus.FOUND, needs_validation=False))
                    else:
                        validated_discoveries.append(replace(discovery, status=DiscoveryStatus.AMBIGUOUS))
                discoveries = tuple(validated_discoveries)

        pending = tuple(
            item for item in validations
            if item.verification_status == VerificationStatus.PENDING_CONFIRMATION
        )
        rejected = tuple(
            item for item in validations
            if item.verification_status == VerificationStatus.REJECTED
        )
        return SourceDiscoveryResult(
            identity,
            self._search.name,
            queries,
            tuple(candidates_by_url.values()),
            tuple(validations),
            official.domain if official else None,
            tuple(discoveries),
            tuple(dict.fromkeys(saved_ids)),
            pending,
            rejected,
            domain_evidence,
            tuple(warnings),
            tuple(errors),
        )

    def _fetch_evidence(self, url: str) -> PageEvidence | None:
        fetched = self._fetcher.fetch(FetchPageRequest(url))
        audit = {"url": url, "final_url": fetched.final_url, "http_status": fetched.http_status,
                 "fetch_status": fetched.fetch_status.value, "error_code": fetched.error_code}
        self.fetch_audit.append(audit)
        if fetched.fetch_status != FetchStatus.SUCCESS or not fetched.raw_html:
            return PageEvidence(
                fetched.final_url or url, fetched.page_title, "", fetched.raw_html or "",
                fetched.fetch_status,
            )
        cleaned = clean_page(CleanPageRequest(fetched.raw_html, fetched.final_url or url))
        audit.update(clean_status=cleaned.clean_status.value, content_length=cleaned.content_length,
                     page_title=cleaned.page_title)
        return PageEvidence(
            fetched.final_url or url,
            cleaned.page_title or fetched.page_title,
            cleaned.clean_content,
            fetched.raw_html,
            fetched.fetch_status,
        )

    def _save_verified(
        self, identity, validation: OfficialSourceValidation
    ) -> int:
        now = datetime.now(UTC).replace(tzinfo=None)
        with self._persistence.transaction() as session:
            competitor = self._persistence.competitors.get_by_normalized_name(
                session, identity.normalized_name
            )
            if competitor is None:
                competitor_id = self._persistence.competitors.create(
                    session,
                    canonical_name=identity.original_name,
                    normalized_name=identity.normalized_name,
                    aliases=list(identity.aliases),
                    official_domain=validation.domain,
                )
            else:
                competitor_id = competitor["id"]
                self._persistence.competitors.update_official_domain(
                    session, competitor_id, validation.domain
                )
            existing = self._persistence.sources.find_by_normalized_url(
                session, competitor_id, validation.normalized_url
            )
            if existing:
                self._persistence.sources.update_verification(
                    session,
                    existing["id"],
                    source_type=validation.source_type.value,
                    url=validation.candidate_url,
                    normalized_url=validation.normalized_url,
                    domain=validation.domain,
                    verification_status=VerificationStatus.VERIFIED.value,
                    verification_reason=validation.verification_reason,
                    confidence=validation.confidence,
                    verified_at=now,
                )
                return existing["id"]
            return self._persistence.sources.create(
                session,
                competitor_id=competitor_id,
                source_type=validation.source_type.value,
                url=validation.candidate_url,
                normalized_url=validation.normalized_url,
                domain=validation.domain,
                verification_status=VerificationStatus.VERIFIED.value,
                verification_reason=validation.verification_reason,
                confidence=validation.confidence,
                verified_at=now,
            )

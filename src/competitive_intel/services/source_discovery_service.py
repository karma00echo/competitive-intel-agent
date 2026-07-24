"""Bounded deterministic competitor source-discovery orchestration."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from competitive_intel.domain.content_cleaner import clean_page
from competitive_intel.domain.names import normalize_competitor_name
from competitive_intel.domain.official_validation import validate_official_source
from competitive_intel.domain.query_generator import generate_search_queries
from competitive_intel.domain.search import SearchIntent, SearchRequest, SearchResult
from competitive_intel.domain.source_discovery import discover_sources
from competitive_intel.domain.sources import (
    DiscoveryStatus,
    OfficialSourceValidation,
    PageEvidence,
    SourceDiscoveryLimits,
    SourceDiscoveryResult,
    SourceType,
    VerificationStatus,
)
from competitive_intel.domain.urls import normalize_url
from competitive_intel.domain.webpage import (
    CleanPageRequest,
    FetchPageRequest,
    FetchStatus,
)
from competitive_intel.infrastructure.search.base import SearchProvider
from competitive_intel.infrastructure.search.search_web import search_web
from competitive_intel.persistence import Persistence


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

    def discover(
        self,
        competitor_name: str,
        *,
        aliases: tuple[str, ...] = (),
        locale: str = "en-US",
        language: str | None = None,
    ) -> SourceDiscoveryResult:
        identity = normalize_competitor_name(competitor_name, aliases)
        lang = language or (
            "zh" if any("\u4e00" <= c <= "\u9fff" for c in competitor_name) else "en"
        )
        queries = generate_search_queries(
            identity,
            SearchIntent.OFFICIAL_SITE,
            language=lang,
            max_queries=self._limits.max_queries_per_intent,
        )
        errors: list[str] = []
        warnings: list[str] = []
        candidates_by_url: dict[str, SearchResult] = {}
        executed: set[str] = set()
        for query in queries:
            if query in executed:
                continue
            executed.add(query)
            response = search_web(
                self._search,
                SearchRequest(
                    query,
                    SearchIntent.OFFICIAL_SITE,
                    locale,
                    lang,
                    self._limits.max_results_per_query,
                ),
            )
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
        for result in tuple(candidates_by_url.values())[: self._limits.max_official_validations]:
            preliminary = validate_official_source(identity, result)
            if preliminary.verification_status == VerificationStatus.REJECTED:
                validations.append(preliminary)
                continue
            page = self._fetch_evidence(result.url)
            if page is not None:
                page_cache[normalize_url(page.final_url)] = page
            validations.append(validate_official_source(identity, result, page))
        if len(candidates_by_url) > self._limits.max_official_validations:
            warnings.append("Official validation limit reached.")

        verified = [
            item for item in validations
            if item.verification_status == VerificationStatus.VERIFIED
        ]
        verified_domains = {item.domain for item in verified}
        if len(verified_domains) > 1:
            warnings.append("Multiple plausible official domains require confirmation.")
            validations = [
                replace(
                    item,
                    verification_status=VerificationStatus.PENDING_CONFIRMATION,
                    verification_reason=(
                        "Multiple independently plausible official domains were found."
                    ),
                )
                if item.verification_status == VerificationStatus.VERIFIED else item
                for item in validations
            ]
            verified = []

        official = max(verified, key=lambda item: item.confidence, default=None)
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
                )
                validated_discoveries = []
                for discovery in discoveries:
                    if (
                        discovery.status != DiscoveryStatus.FOUND
                        or not discovery.candidate_url
                    ):
                        validated_discoveries.append(discovery)
                        continue
                    if discovery.source_type == SourceType.HOMEPAGE:
                        validation = official
                    else:
                        synthetic = SearchResult(
                            discovery.source_type.value,
                            discovery.candidate_url,
                            "Discovered from verified official homepage.",
                            1,
                            self._search.name,
                            "internal discovery",
                        )
                        validation = validate_official_source(
                            identity,
                            synthetic,
                            self._fetch_evidence(discovery.candidate_url),
                            source_type=discovery.source_type,
                        )
                        validations.append(validation)
                    if validation.verification_status == VerificationStatus.VERIFIED:
                        saved_ids.append(self._save_verified(identity, validation))
                        validated_discoveries.append(replace(discovery, needs_validation=False))
                    else:
                        validated_discoveries.append(
                            replace(discovery, status=DiscoveryStatus.AMBIGUOUS)
                        )
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
            tuple(warnings),
            tuple(errors),
        )

    def _fetch_evidence(self, url: str) -> PageEvidence | None:
        fetched = self._fetcher.fetch(FetchPageRequest(url))
        if fetched.fetch_status != FetchStatus.SUCCESS or not fetched.raw_html:
            return PageEvidence(
                fetched.final_url or url, fetched.page_title, "", fetched.raw_html or "",
                fetched.fetch_status,
            )
        cleaned = clean_page(CleanPageRequest(fetched.raw_html, fetched.final_url or url))
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

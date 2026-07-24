"""Source validation and discovery data contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .search import SearchResult
from .webpage import FetchStatus


class SourceType(StrEnum):
    HOMEPAGE = "HOMEPAGE"
    FEATURES = "FEATURES"
    PRICING = "PRICING"
    CHANGELOG = "CHANGELOG"


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"


class DiscoveryStatus(StrEnum):
    FOUND = "FOUND"
    NOT_FOUND = "NOT_FOUND"
    AMBIGUOUS = "AMBIGUOUS"
    UNSUPPORTED = "UNSUPPORTED"


@dataclass(frozen=True, slots=True)
class CompetitorIdentity:
    original_name: str
    normalized_name: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PageEvidence:
    final_url: str
    page_title: str | None
    clean_content: str
    raw_html: str
    fetch_status: FetchStatus


@dataclass(frozen=True, slots=True)
class OfficialSourceValidation:
    candidate_url: str
    normalized_url: str
    domain: str
    verification_status: VerificationStatus
    source_type: SourceType
    confidence: float
    supporting_signals: tuple[str, ...]
    risk_signals: tuple[str, ...]
    verification_reason: str


@dataclass(frozen=True, slots=True)
class DiscoveredSource:
    source_type: SourceType
    candidate_url: str | None
    normalized_url: str | None
    discovery_method: str
    matched_signals: tuple[str, ...]
    confidence: float
    needs_validation: bool
    status: DiscoveryStatus


@dataclass(frozen=True, slots=True)
class SourceDiscoveryLimits:
    max_queries_per_intent: int = 3
    max_results_per_query: int = 10
    max_candidate_urls: int = 20
    max_official_validations: int = 10
    max_internal_links: int = 100
    max_supplemental_searches: int = 3
    max_pages: int = 8


@dataclass(frozen=True, slots=True)
class SourceDiscoveryResult:
    identity: CompetitorIdentity
    provider: str
    queries: tuple[str, ...]
    candidates: tuple[SearchResult, ...]
    validations: tuple[OfficialSourceValidation, ...]
    official_domain: str | None
    discoveries: tuple[DiscoveredSource, ...]
    saved_source_ids: tuple[int, ...]
    pending: tuple[OfficialSourceValidation, ...]
    rejected: tuple[OfficialSourceValidation, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

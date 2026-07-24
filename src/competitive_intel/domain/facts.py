"""Structured fact contracts and finite schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class FactCategory(StrEnum):
    POSITIONING = "POSITIONING"
    FEATURE = "FEATURE"
    PLAN = "PLAN"
    PRICE = "PRICE"
    PRODUCT_UPDATE = "PRODUCT_UPDATE"


class StatementType(StrEnum):
    FACT = "FACT"


class EvidenceCheckStatus(StrEnum):
    CONFIRMED = "CONFIRMED"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTING = "CONFLICTING"
    INVALID_SCHEMA = "INVALID_SCHEMA"
    DUPLICATE = "DUPLICATE"


class FeatureCategory(StrEnum):
    COLLABORATION = "COLLABORATION"
    DOCUMENTS = "DOCUMENTS"
    PROJECT_MANAGEMENT = "PROJECT_MANAGEMENT"
    AI = "AI"
    SEARCH = "SEARCH"
    MEETINGS = "MEETINGS"
    COMMUNICATION = "COMMUNICATION"
    AUTOMATION = "AUTOMATION"
    INTEGRATION = "INTEGRATION"
    SECURITY = "SECURITY"
    OTHER = "OTHER"


class FeatureStatus(StrEnum):
    AVAILABLE = "AVAILABLE"
    COMING_SOON = "COMING_SOON"
    BETA = "BETA"
    DEPRECATED = "DEPRECATED"
    UNKNOWN = "UNKNOWN"


class PlanPublicStatus(StrEnum):
    PUBLIC = "PUBLIC"
    CONTACT_SALES = "CONTACT_SALES"
    FREE = "FREE"
    TRIAL = "TRIAL"
    UNKNOWN = "UNKNOWN"


class PricePublicStatus(StrEnum):
    PUBLIC = "PUBLIC"
    CONTACT_SALES = "CONTACT_SALES"
    NOT_DISCLOSED = "NOT_DISCLOSED"
    FREE = "FREE"
    UNKNOWN = "UNKNOWN"


class BillingPeriod(StrEnum):
    MONTH = "MONTH"
    YEAR = "YEAR"
    ONE_TIME = "ONE_TIME"
    USAGE_BASED = "USAGE_BASED"
    UNKNOWN = "UNKNOWN"


class BillingUnit(StrEnum):
    USER = "USER"
    WORKSPACE = "WORKSPACE"
    ORGANIZATION = "ORGANIZATION"
    USAGE = "USAGE"
    FLAT = "FLAT"
    UNKNOWN = "UNKNOWN"


class BillingCommitment(StrEnum):
    MONTHLY_BILLING = "MONTHLY_BILLING"
    ANNUAL_BILLING = "ANNUAL_BILLING"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class CandidateFact:
    fact_category: FactCategory
    fact_value: dict[str, Any]
    value_text: str
    evidence_text: str
    confidence: float
    statement_type: str = "FACT"
    fact_key: str | None = None
    extraction_warnings: tuple[str, ...] = ()
    competitor_id: int | None = None
    source_id: int | None = None
    snapshot_id: int | None = None
    source_url: str | None = None
    evidence_status: EvidenceCheckStatus | None = None


@dataclass(frozen=True, slots=True)
class EvidenceCheckResult:
    status: EvidenceCheckStatus
    reason: str
    fact_key: str | None = None


@dataclass(frozen=True, slots=True)
class RejectedFact:
    candidate: CandidateFact | None
    status: EvidenceCheckStatus
    reason: str
    source_url: str
    snapshot_id: int


@dataclass(frozen=True, slots=True)
class SavedFact:
    fact_id: int
    source_id: int
    snapshot_id: int
    category: FactCategory
    fact_key: str
    fact_value: dict[str, Any]
    evidence_text: str
    source_url: str
    confidence: float
    evidence_status: EvidenceCheckStatus = EvidenceCheckStatus.CONFIRMED
    extraction_warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class FactExtractionLimits:
    max_facts_per_page: int = 25
    max_pages: int = 8
    max_input_characters: int = 50_000
    max_model_calls: int = 8


@dataclass(frozen=True, slots=True)
class FactExtractionResult:
    competitor_name: str
    competitor_id: int | None
    run_id: int | None
    provider: str
    source_ids: tuple[int, ...]
    snapshot_ids: tuple[int, ...]
    candidate_count: int
    saved: tuple[SavedFact, ...]
    rejected: tuple[RejectedFact, ...]
    duplicate_count: int
    warnings: tuple[str, ...]
    errors: tuple[str, ...]

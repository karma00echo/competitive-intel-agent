from __future__ import annotations

import pytest

from competitive_intel.domain.evidence import EvidenceChecker
from competitive_intel.domain.fact_normalization import normalize_fact
from competitive_intel.domain.fact_schema import validate_fact_schema
from competitive_intel.domain.facts import (
    CandidateFact, EvidenceCheckStatus, FactCategory,
)


def _price(**updates) -> CandidateFact:
    evidence_text = updates.pop(
        "evidence_text",
        "Plus plan costs $10 per user / month, billed annually.",
    )
    value = {
        "plan_name": "Plus", "amount": "10.00", "currency": "USD",
        "billing_period": "MONTH", "billing_unit": "USER",
        "billing_commitment": "ANNUAL_BILLING", "region": None,
        "tax_status": "UNKNOWN", "public_status": "PUBLIC",
    }
    value.update(updates)
    return CandidateFact(
        FactCategory.PRICE, value, "$10 per user / month",
        evidence_text, 0.99,
    )


def test_price_normalization_and_key_keep_billing_dimensions_separate() -> None:
    annual = normalize_fact(_price())
    monthly = normalize_fact(
        _price(amount="12", billing_commitment="MONTHLY_BILLING")
    )
    workspace = normalize_fact(_price(billing_unit="WORKSPACE"))

    assert annual.fact_value["amount"] == "10"
    assert annual.fact_key != monthly.fact_key
    assert annual.fact_key != workspace.fact_key
    assert annual.fact_key == "price.plus.month.user.annual_billing"


def test_contact_sales_requires_null_amount_and_undisclosed_is_not_zero() -> None:
    contact = _price(
        plan_name="Enterprise", amount=None, currency=None,
        billing_period="UNKNOWN", billing_unit="UNKNOWN",
        billing_commitment="UNKNOWN", public_status="CONTACT_SALES",
    )
    invalid_contact = _price(public_status="CONTACT_SALES")
    undisclosed_zero = _price(public_status="NOT_DISCLOSED", amount="0")

    assert validate_fact_schema(contact)[0]
    assert not validate_fact_schema(invalid_contact)[0]
    assert not validate_fact_schema(undisclosed_zero)[0]


def test_invalid_feature_enum_is_invalid_schema() -> None:
    candidate = CandidateFact(
        FactCategory.FEATURE,
        {
            "feature_name": "Docs", "normalized_feature_name": "docs",
            "feature_description": "Docs", "feature_category": "MAGIC",
            "availability": None, "related_plan": None, "status": "AVAILABLE",
        },
        "Docs", "Docs are available.", 0.9,
    )
    check = EvidenceChecker().check(candidate, "Docs are available.", "https://x")
    assert check.status == EvidenceCheckStatus.INVALID_SCHEMA


@pytest.mark.parametrize(
    ("category", "value"),
    [
        (
            FactCategory.POSITIONING,
            {
                "primary_positioning": "Connected workspace",
                "target_users": ["teams"],
                "primary_use_cases": ["docs"],
                "deployment_type": None,
                "public_description": "Connected workspace for teams.",
            },
        ),
        (
            FactCategory.FEATURE,
            {
                "feature_name": "Docs",
                "normalized_feature_name": "docs",
                "feature_description": "Collaborative documents",
                "feature_category": "DOCUMENTS",
                "availability": None,
                "related_plan": None,
                "status": "AVAILABLE",
            },
        ),
        (
            FactCategory.PLAN,
            {
                "plan_name": "Plus",
                "normalized_plan_name": "plus",
                "plan_description": "Plus plan",
                "target_user": None,
                "included_features": ["Docs"],
                "public_status": "PUBLIC",
            },
        ),
        (
            FactCategory.PRICE,
            {
                "plan_name": "Plus",
                "amount": "10.00",
                "currency": "USD",
                "billing_period": "MONTH",
                "billing_unit": "USER",
                "billing_commitment": "ANNUAL_BILLING",
                "region": None,
                "tax_status": "UNKNOWN",
                "public_status": "PUBLIC",
            },
        ),
        (
            FactCategory.PRODUCT_UPDATE,
            {
                "update_title": "Enterprise Search",
                "published_date": "2026-07-15",
                "update_type": "FEATURE_RELEASE",
                "affected_features": ["Search"],
                "summary": "Enterprise Search is available.",
                "availability": "AVAILABLE",
                "status": "AVAILABLE",
            },
        ),
    ],
)
def test_each_supported_fact_schema_accepts_valid_structured_values(
    category, value
) -> None:
    candidate = CandidateFact(category, value, "value", "evidence", 0.9)
    assert validate_fact_schema(candidate) == (True, "")


def test_invalid_price_amount_returns_invalid_schema_without_normalization_error() -> None:
    candidate = _price(amount="not-a-number")
    result = EvidenceChecker().check(
        candidate, candidate.evidence_text, "https://x"
    )
    assert result.status == EvidenceCheckStatus.INVALID_SCHEMA


def test_exact_evidence_confirms_and_missing_evidence_is_rejected() -> None:
    candidate = _price()
    checker = EvidenceChecker()
    content = "Pricing\nPlus plan costs $10 per user / month, billed annually."

    assert checker.check(candidate, content, "https://x").status == EvidenceCheckStatus.CONFIRMED
    assert checker.check(candidate, "Different text", "https://x").status == EvidenceCheckStatus.INSUFFICIENT_EVIDENCE


def test_price_conflict_detects_wrong_amount_currency_or_commitment() -> None:
    evidence = "Plus plan costs €12 per workspace / month, billed monthly."
    candidate = _price(
        amount="10", currency="USD", billing_unit="USER",
        billing_commitment="ANNUAL_BILLING",
        evidence_text=evidence,
    )
    assert EvidenceChecker().check(candidate, evidence, "https://x").status == EvidenceCheckStatus.CONFLICTING


def test_duplicate_fact_key_is_reported() -> None:
    candidate = normalize_fact(_price())
    result = EvidenceChecker().check(
        candidate, candidate.evidence_text, "https://x",
        existing_keys={candidate.fact_key or ""},
    )
    assert result.status == EvidenceCheckStatus.DUPLICATE


def test_product_update_allows_missing_date_without_using_fetch_date() -> None:
    candidate = CandidateFact(
        FactCategory.PRODUCT_UPDATE,
        {
            "update_title": "New Search", "published_date": None,
            "update_type": "FEATURE_RELEASE", "affected_features": ["Search"],
            "summary": "New Search is available.", "availability": "AVAILABLE",
            "status": "AVAILABLE",
        },
        "New Search", "New Search is available.", 0.9,
    )
    assert validate_fact_schema(candidate)[0]
    assert normalize_fact(candidate).fact_key.startswith("product_update.undated_")


def test_product_update_requires_the_explicit_full_date_in_evidence() -> None:
    candidate = CandidateFact(
        FactCategory.PRODUCT_UPDATE,
        {
            "update_title": "Enterprise Search",
            "published_date": "2026-07-15",
            "update_type": "FEATURE_RELEASE",
            "affected_features": ["Search"],
            "summary": "Enterprise Search is available.",
            "availability": "AVAILABLE",
            "status": "AVAILABLE",
        },
        "Enterprise Search",
        "In 2026, Enterprise Search is available.",
        0.9,
    )
    result = EvidenceChecker().check(
        candidate, candidate.evidence_text, "https://x"
    )
    assert result.status == EvidenceCheckStatus.CONFLICTING

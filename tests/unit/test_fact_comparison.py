from __future__ import annotations

from competitive_intel.domain.fact_comparison import (
    ChangeType,
    FactComparisonService,
    FactNormalizer,
)


def _fact(
    fact_id: int,
    category: str,
    key: str,
    value,
    *,
    source_id: int = 1,
):
    return {
        "id": fact_id,
        "fact_category": category,
        "fact_key": key,
        "fact_value": value,
        "normalized_value": value,
        "source_id": source_id,
        "source_url": "https://example.com",
        "evidence_text": "Evidence",
        "confidence": 0.9,
    }


def test_price_normalization_ignores_format_but_not_unknown_semantics() -> None:
    normalizer = FactNormalizer()
    left = normalizer.normalize(
        "PRICE",
        {
            "amount": "10.00",
            "currency": "usd",
            "billing_period": "month",
            "billing_unit": "user",
            "billing_commitment": "annual_billing",
        },
    )
    right = normalizer.normalize(
        "PRICE",
        {
            "billing_commitment": "ANNUAL_BILLING",
            "billing_unit": "USER",
            "billing_period": "MONTH",
            "currency": "USD",
            "amount": 10,
        },
    )
    assert left == right
    assert normalizer.normalize("PRICE", {"amount": None}) != (
        normalizer.normalize("PRICE", {"amount": "UNKNOWN"})
    )


def test_plan_feature_positioning_and_update_normalization() -> None:
    normalizer = FactNormalizer()
    assert normalizer.normalize(
        "PLAN",
        {
            "plan_name": " Plus ",
            "public_status": "public",
            "included_features": ["AI", "Docs"],
        },
    ) == normalizer.normalize(
        "PLAN",
        {
            "included_features": ["Docs", "AI"],
            "public_status": "PUBLIC",
            "plan_name": "Plus",
        },
    )
    feature = normalizer.normalize(
        "FEATURE",
        {
            "feature_name": " Enterprise   Search ",
            "status": "available",
            "availability": "public",
            "related_plan": " Plus ",
        },
    )
    assert feature["feature_name"] == "enterprise search"
    assert feature["status"] == "AVAILABLE"
    assert normalizer.normalize(
        "POSITIONING", {"target_users": ["Teams", "Enterprise"]}
    ) == normalizer.normalize(
        "POSITIONING", {"target_users": ["Enterprise", "Teams"]}
    )
    assert normalizer.normalize(
        "PRODUCT_UPDATE",
        {
            "published_date": "2026-07-15",
            "update_title": " Enterprise Search ",
            "update_type": "feature_release",
        },
    )["update_type"] == "FEATURE_RELEASE"


def test_comparison_distinguishes_all_five_core_states() -> None:
    previous = [
        _fact(1, "PRICE", "price.plus", {"amount": "10"}, source_id=1),
        _fact(2, "FEATURE", "feature.docs", {"status": "AVAILABLE"}, source_id=1),
        _fact(3, "FEATURE", "feature.removed", {"status": "AVAILABLE"}, source_id=2),
        _fact(4, "PLAN", "plan.unknown", {"public_status": "PUBLIC"}, source_id=3),
    ]
    current = [
        _fact(5, "PRICE", "price.plus", {"amount": "12"}, source_id=1),
        _fact(2, "FEATURE", "feature.docs", {"status": "available"}, source_id=1),
        _fact(6, "FEATURE", "feature.new", {"status": "AVAILABLE"}, source_id=1),
    ]
    result = FactComparisonService().compare(
        competitor_id=1,
        current_run_id=2,
        previous_successful_run_id=1,
        current_facts=current,
        previous_facts=previous,
        source_fetch_results={1: True, 2: True, 3: False},
    )
    assert [item.change_type for item in result.modified] == [ChangeType.MODIFIED]
    assert [item.fact_key for item in result.unchanged] == ["feature.docs"]
    assert [item.fact_key for item in result.added] == ["feature.new"]
    assert [item.fact_key for item in result.removed] == ["feature.removed"]
    assert [item.fact_key for item in result.uncomparable] == ["plan.unknown"]
    assert result.summary_counts == {
        "added_count": 1,
        "removed_count": 1,
        "modified_count": 1,
        "unchanged_count": 1,
        "uncomparable_count": 1,
    }

"""Deterministic validation of candidate fact payloads."""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from .facts import (
    BillingCommitment, BillingPeriod, BillingUnit, CandidateFact,
    FactCategory, FeatureCategory, FeatureStatus, PlanPublicStatus,
    PricePublicStatus,
)


REQUIRED = {
    FactCategory.POSITIONING: ("primary_positioning", "target_users", "primary_use_cases", "deployment_type", "public_description"),
    FactCategory.FEATURE: ("feature_name", "normalized_feature_name", "feature_description", "feature_category", "availability", "related_plan", "status"),
    FactCategory.PLAN: ("plan_name", "normalized_plan_name", "plan_description", "target_user", "included_features", "public_status"),
    FactCategory.PRICE: ("plan_name", "amount", "currency", "billing_period", "billing_unit", "billing_commitment", "region", "tax_status", "public_status"),
    FactCategory.PRODUCT_UPDATE: ("update_title", "published_date", "update_type", "affected_features", "summary", "availability", "status"),
}


def _enum(value: Any, enum_type) -> bool:
    try:
        enum_type(value)
        return True
    except (ValueError, TypeError):
        return False


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _optional_string(value: Any) -> bool:
    return value is None or isinstance(value, str)


def _string_list(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def validate_fact_schema(candidate: CandidateFact) -> tuple[bool, str]:
    if candidate.statement_type != "FACT":
        return False, "Only FACT statement_type may be persisted."
    if not 0 <= candidate.confidence <= 1:
        return False, "confidence must be between zero and one."
    missing = [key for key in REQUIRED[candidate.fact_category] if key not in candidate.fact_value]
    if missing:
        return False, f"Missing required fields: {', '.join(missing)}"
    value = candidate.fact_value
    if candidate.fact_category == FactCategory.POSITIONING:
        if not all((
            _non_empty_string(value["primary_positioning"]),
            _string_list(value["target_users"]),
            _string_list(value["primary_use_cases"]),
            _optional_string(value["deployment_type"]),
            _non_empty_string(value["public_description"]),
        )):
            return False, "Invalid positioning field type or empty required text."
    elif candidate.fact_category == FactCategory.FEATURE:
        if not all((
            _non_empty_string(value["feature_name"]),
            _non_empty_string(value["normalized_feature_name"]),
            _non_empty_string(value["feature_description"]),
            _optional_string(value["availability"]),
            _optional_string(value["related_plan"]),
        )):
            return False, "Invalid feature field type or empty required text."
        if not _enum(value["feature_category"], FeatureCategory) or not _enum(value["status"], FeatureStatus):
            return False, "Invalid feature_category or feature status."
    elif candidate.fact_category == FactCategory.PLAN:
        if not all((
            _non_empty_string(value["plan_name"]),
            _non_empty_string(value["normalized_plan_name"]),
            _non_empty_string(value["plan_description"]),
            _optional_string(value["target_user"]),
            _string_list(value["included_features"]),
        )):
            return False, "Invalid plan field type or empty required text."
        if not _enum(value["public_status"], PlanPublicStatus):
            return False, "Invalid plan public_status."
    elif candidate.fact_category == FactCategory.PRICE:
        if not all((
            _non_empty_string(value["plan_name"]),
            _optional_string(value["currency"]),
            _optional_string(value["region"]),
            _non_empty_string(value["tax_status"]),
        )):
            return False, "Invalid price field type or empty required text."
        if not all((
            _enum(value["billing_period"], BillingPeriod),
            _enum(value["billing_unit"], BillingUnit),
            _enum(value["billing_commitment"], BillingCommitment),
            _enum(value["public_status"], PricePublicStatus),
        )):
            return False, "Invalid price enum."
        amount = value["amount"]
        if amount is not None:
            try:
                decimal_amount = Decimal(str(amount))
            except (InvalidOperation, ValueError, TypeError):
                return False, "Price amount must be a numeric string or null."
            if not decimal_amount.is_finite() or decimal_amount < 0:
                return False, "Price amount must be finite and non-negative."
        if value["public_status"] == "CONTACT_SALES" and amount is not None:
            return False, "Contact Sales price amount must be null."
        if value["public_status"] == "NOT_DISCLOSED" and str(amount) == "0":
            return False, "Undisclosed price must not become zero."
    elif candidate.fact_category == FactCategory.PRODUCT_UPDATE:
        if not all((
            _non_empty_string(value["update_title"]),
            _non_empty_string(value["update_type"]),
            _string_list(value["affected_features"]),
            _non_empty_string(value["summary"]),
            _optional_string(value["availability"]),
            _non_empty_string(value["status"]),
        )):
            return False, "Invalid product update field type or empty required text."
        published = value["published_date"]
        if published:
            try:
                date.fromisoformat(published)
            except (TypeError, ValueError):
                return False, "published_date must be ISO date or null."
    return True, ""

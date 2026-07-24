"""Stable fact values and keys for later history comparison."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from decimal import Decimal
from typing import Any

from .facts import CandidateFact, FactCategory


def slug(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"[^\w\u4e00-\u9fff]+", "_", value)
    return value.strip("_") or "unknown"


def normalize_fact(candidate: CandidateFact) -> CandidateFact:
    value: dict[str, Any] = dict(candidate.fact_value)
    for key in ("normalized_feature_name", "normalized_plan_name"):
        if key in value and value[key]:
            value[key] = slug(str(value[key]))
    if candidate.fact_category == FactCategory.PRICE and value.get("amount") is not None:
        amount = Decimal(str(value["amount"]))
        value["amount"] = format(amount.normalize(), "f")
    category = candidate.fact_category
    if category == FactCategory.POSITIONING:
        key = "positioning.primary"
    elif category == FactCategory.FEATURE:
        key = f"feature.{slug(str(value['normalized_feature_name']))}"
    elif category == FactCategory.PLAN:
        key = f"plan.{slug(str(value['normalized_plan_name']))}"
    elif category == FactCategory.PRICE:
        key = ".".join((
            "price", slug(str(value["plan_name"])),
            str(value["billing_period"]).casefold(),
            str(value["billing_unit"]).casefold(),
            str(value["billing_commitment"]).casefold(),
        ))
    else:
        date_part = value.get("published_date") or "undated"
        key = f"product_update.{slug(str(date_part))}_{slug(str(value['update_title']))}"
    return replace(
        candidate,
        fact_value=value,
        value_text=candidate.value_text.strip(),
        evidence_text=candidate.evidence_text.strip(),
        fact_key=key,
    )

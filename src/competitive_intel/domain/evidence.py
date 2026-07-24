"""Deterministic evidence validation; no semantic-model fallback."""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from .fact_normalization import normalize_fact
from .fact_schema import validate_fact_schema
from .facts import (
    CandidateFact, EvidenceCheckResult, EvidenceCheckStatus, FactCategory,
)


def normalized_evidence(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


class EvidenceChecker:
    def check(
        self,
        candidate: CandidateFact,
        clean_content: str,
        source_url: str,
        *,
        existing_keys: set[str] | None = None,
    ) -> EvidenceCheckResult:
        valid, reason = validate_fact_schema(candidate)
        if not valid:
            return EvidenceCheckResult(EvidenceCheckStatus.INVALID_SCHEMA, reason)
        fact = normalize_fact(candidate)
        if existing_keys is not None and fact.fact_key in existing_keys:
            return EvidenceCheckResult(
                EvidenceCheckStatus.DUPLICATE,
                "The normalized fact_key already exists for this snapshot.",
                fact.fact_key,
            )
        evidence = normalized_evidence(fact.evidence_text)
        content = normalized_evidence(clean_content)
        if not evidence or evidence not in content:
            return EvidenceCheckResult(
                EvidenceCheckStatus.INSUFFICIENT_EVIDENCE,
                "Exact normalized evidence text was not found in snapshot clean_content.",
                fact.fact_key,
            )
        value = fact.fact_value
        key_values: list[str] = []
        if fact.fact_category == FactCategory.FEATURE:
            key_values.append(str(value["feature_name"]))
        elif fact.fact_category == FactCategory.PLAN:
            key_values.append(str(value["plan_name"]))
        elif fact.fact_category == FactCategory.PRICE:
            key_values.append(str(value["plan_name"]))
            if value["amount"] is not None:
                amount = re.escape(str(value["amount"]))
                if not re.search(
                    rf"(?<![\d.]){amount}(?:\.0+)?(?![\d.])", evidence
                ):
                    return EvidenceCheckResult(
                        EvidenceCheckStatus.CONFLICTING,
                        "Price amount is not supported by the evidence.",
                        fact.fact_key,
                    )
            if value["currency"]:
                symbols = {"USD": ("$", "usd"), "EUR": ("€", "eur"), "CNY": ("¥", "cny", "rmb")}
                if not any(item in evidence for item in symbols.get(str(value["currency"]).upper(), (str(value["currency"]).casefold(),))):
                    return EvidenceCheckResult(
                        EvidenceCheckStatus.CONFLICTING,
                        "Price currency is not supported by the evidence.",
                        fact.fact_key,
                    )
            required_signals = {
                "MONTH": ("month", "monthly", "月"),
                "YEAR": ("year", "annual", "年"),
                "USER": ("user", "用户"),
                "WORKSPACE": ("workspace", "工作区"),
                "ANNUAL_BILLING": ("billed annually", "annual billing", "年付"),
                "MONTHLY_BILLING": ("billed monthly", "monthly billing", "月付"),
            }
            for enum_value in (
                value["billing_period"], value["billing_unit"],
                value["billing_commitment"],
            ):
                signals = required_signals.get(str(enum_value), ())
                if signals and not any(signal in evidence for signal in signals):
                    return EvidenceCheckResult(
                        EvidenceCheckStatus.CONFLICTING,
                        f"Price dimension {enum_value} is not supported by evidence.",
                        fact.fact_key,
                    )
        elif fact.fact_category == FactCategory.PRODUCT_UPDATE:
            key_values.append(str(value["update_title"]))
            if value["published_date"]:
                published = date.fromisoformat(str(value["published_date"]))
                date_signals = (
                    published.isoformat(),
                    f"{published.strftime('%B')} {published.day}, {published.year}",
                    f"{published.strftime('%B')} {published.day} {published.year}",
                    f"{published.day} {published.strftime('%B')} {published.year}",
                )
                if not any(signal.casefold() in evidence for signal in date_signals):
                    return EvidenceCheckResult(
                        EvidenceCheckStatus.CONFLICTING,
                        "Published date is not supported by the evidence.",
                        fact.fact_key,
                    )
        else:
            key_values.append(str(value["primary_positioning"]))
        for key_value in key_values:
            if normalized_evidence(key_value) not in evidence:
                return EvidenceCheckResult(
                    EvidenceCheckStatus.CONFLICTING,
                    f"Critical value {key_value!r} is not present in evidence.",
                    fact.fact_key,
                )
        return EvidenceCheckResult(
            EvidenceCheckStatus.CONFIRMED,
            "Schema and exact snapshot evidence are valid.",
            fact.fact_key,
        )

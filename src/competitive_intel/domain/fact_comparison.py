"""Deterministic business-value normalization and fact comparison."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any, Mapping, Sequence


class ChangeType(StrEnum):
    ADDED = "ADDED"
    REMOVED = "REMOVED"
    MODIFIED = "MODIFIED"
    UNCHANGED = "UNCHANGED"
    UNCOMPARABLE = "UNCOMPARABLE"


def _text(value: Any, *, upper: bool = False) -> Any:
    if not isinstance(value, str):
        return value
    normalized = unicodedata.normalize("NFKC", value)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.upper() if upper else normalized


def _identity_text(value: Any) -> Any:
    normalized = _text(value)
    return normalized.casefold() if isinstance(normalized, str) else normalized


def _json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


class FactNormalizer:
    """Normalize only business semantics; evidence metadata is intentionally ignored."""

    ENUM_FIELDS = {
        "currency",
        "billing_period",
        "billing_unit",
        "billing_commitment",
        "public_status",
        "status",
        "availability",
        "update_type",
        "feature_category",
    }
    SET_FIELDS = {
        "included_features",
        "capabilities",
        "target_users",
        "use_cases",
        "related_plans",
    }

    def normalize(self, category: str, value: Any) -> dict[str, Any]:
        raw = _json_value(value)
        if not isinstance(raw, Mapping):
            raw = {"value": raw}
        normalized = self._normalize_mapping(raw)
        if category == "PRICE" and normalized.get("amount") is not None:
            try:
                amount = Decimal(str(normalized["amount"]))
                normalized["amount"] = format(amount.normalize(), "f")
            except (InvalidOperation, ValueError):
                normalized["amount"] = _text(normalized["amount"])
        if category == "FEATURE":
            for key in ("feature_name", "normalized_feature_name"):
                if key in normalized:
                    normalized[key] = _identity_text(normalized[key])
            for key in ("related_plan", "related_plans"):
                if key in normalized:
                    if isinstance(normalized[key], list):
                        normalized[key] = sorted(
                            _identity_text(item) for item in normalized[key]
                        )
                    else:
                        normalized[key] = _identity_text(normalized[key])
        if category == "PLAN" and "plan_name" in normalized:
            normalized["plan_name"] = _identity_text(normalized["plan_name"])
        if category == "PLAN" and "normalized_plan_name" in normalized:
            normalized["normalized_plan_name"] = _identity_text(
                normalized["normalized_plan_name"]
            )
        if category == "POSITIONING":
            normalized = self._normalize_mapping(normalized, sort_all_lists=True)
        if category == "PRODUCT_UPDATE":
            for key in ("published_date", "update_title"):
                if key in normalized:
                    normalized[key] = (
                        _identity_text(normalized[key])
                        if key == "update_title"
                        else _text(normalized[key])
                    )
        return normalized

    def canonical_json(self, category: str, value: Any) -> str:
        return json.dumps(
            self.normalize(category, value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _normalize_mapping(
        self, value: Mapping[str, Any], *, sort_all_lists: bool = False
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key in sorted(value):
            item = value[key]
            if isinstance(item, Mapping):
                result[key] = self._normalize_mapping(item)
            elif isinstance(item, list):
                items = [
                    self._normalize_mapping(part)
                    if isinstance(part, Mapping)
                    else _text(part)
                    for part in item
                ]
                if sort_all_lists or key in self.SET_FIELDS:
                    items.sort(
                        key=lambda part: json.dumps(
                            part, ensure_ascii=False, sort_keys=True
                        ).casefold()
                    )
                result[key] = items
            elif key in self.ENUM_FIELDS:
                result[key] = _text(item, upper=True)
            else:
                result[key] = _text(item)
        return result


@dataclass(frozen=True, slots=True)
class FactChange:
    change_type: ChangeType
    category: str
    fact_key: str
    old_fact_id: int | None
    new_fact_id: int | None
    old_value: Any
    new_value: Any
    old_evidence: str | None
    new_evidence: str | None
    old_source_url: str | None
    new_source_url: str | None
    confidence: float | None
    reason: str
    detected_at: datetime
    run_id: int


@dataclass(frozen=True, slots=True)
class FactComparisonResult:
    added: tuple[FactChange, ...] = ()
    removed: tuple[FactChange, ...] = ()
    modified: tuple[FactChange, ...] = ()
    unchanged: tuple[FactChange, ...] = ()
    uncomparable: tuple[FactChange, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()

    @property
    def all_changes(self) -> tuple[FactChange, ...]:
        return (
            self.added
            + self.removed
            + self.modified
            + self.unchanged
            + self.uncomparable
        )

    @property
    def summary_counts(self) -> dict[str, int]:
        return {
            "added_count": len(self.added),
            "removed_count": len(self.removed),
            "modified_count": len(self.modified),
            "unchanged_count": len(self.unchanged),
            "uncomparable_count": len(self.uncomparable),
        }


class FactComparisonService:
    def __init__(self, normalizer: FactNormalizer | None = None) -> None:
        self._normalizer = normalizer or FactNormalizer()

    def compare(
        self,
        *,
        competitor_id: int,
        current_run_id: int,
        previous_successful_run_id: int,
        current_facts: Sequence[Mapping[str, Any]],
        previous_facts: Sequence[Mapping[str, Any]],
        source_fetch_results: Mapping[int, bool],
        comparison_policy: Mapping[str, Any] | None = None,
    ) -> FactComparisonResult:
        del competitor_id, previous_successful_run_id, comparison_policy
        now = datetime.now(UTC).replace(tzinfo=None)
        current = self._index(current_facts)
        previous = self._index(previous_facts)
        buckets: dict[ChangeType, list[FactChange]] = {
            item: [] for item in ChangeType
        }
        warnings: list[str] = []
        for identity in sorted(set(current) | set(previous)):
            old = previous.get(identity)
            new = current.get(identity)
            category, fact_key = identity
            if old is None:
                change_type = ChangeType.ADDED
                reason = "Fact identity did not exist in the previous successful run."
            elif new is None:
                source_id = int(old.get("source_id") or 0)
                if source_fetch_results.get(source_id) is True:
                    change_type = ChangeType.REMOVED
                    reason = "Fact was absent after its source was fetched successfully."
                else:
                    change_type = ChangeType.UNCOMPARABLE
                    reason = (
                        "Fact absence cannot be trusted because its source did not "
                        "produce a successful current snapshot."
                    )
                    warnings.append(f"{fact_key}: {reason}")
            else:
                old_value = self._normalizer.normalize(
                    category, old.get("normalized_value", old.get("fact_value"))
                )
                new_value = self._normalizer.normalize(
                    category, new.get("normalized_value", new.get("fact_value"))
                )
                if old_value == new_value:
                    change_type = ChangeType.UNCHANGED
                    reason = "Normalized business value is unchanged."
                else:
                    change_type = ChangeType.MODIFIED
                    reason = "Normalized business value changed."
            buckets[change_type].append(
                self._change(
                    change_type, category, fact_key, old, new, now,
                    current_run_id, reason
                )
            )
        return FactComparisonResult(
            added=tuple(buckets[ChangeType.ADDED]),
            removed=tuple(buckets[ChangeType.REMOVED]),
            modified=tuple(buckets[ChangeType.MODIFIED]),
            unchanged=tuple(buckets[ChangeType.UNCHANGED]),
            uncomparable=tuple(buckets[ChangeType.UNCOMPARABLE]),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    @staticmethod
    def _index(
        rows: Sequence[Mapping[str, Any]],
    ) -> dict[tuple[str, str], Mapping[str, Any]]:
        indexed: dict[tuple[str, str], Mapping[str, Any]] = {}
        for row in rows:
            identity = (str(row["fact_category"]), str(row["fact_key"]))
            indexed[identity] = row
        return indexed

    @staticmethod
    def _change(
        change_type: ChangeType,
        category: str,
        fact_key: str,
        old: Mapping[str, Any] | None,
        new: Mapping[str, Any] | None,
        detected_at: datetime,
        run_id: int,
        reason: str,
    ) -> FactChange:
        confidences = [
            float(value)
            for value in (
                old.get("observed_confidence", old.get("confidence")) if old else None,
                new.get("observed_confidence", new.get("confidence")) if new else None,
            )
            if value is not None
        ]
        return FactChange(
            change_type=change_type,
            category=category,
            fact_key=fact_key,
            old_fact_id=int(old["id"]) if old else None,
            new_fact_id=int(new["id"]) if new else None,
            old_value=old.get("normalized_value", old.get("fact_value")) if old else None,
            new_value=new.get("normalized_value", new.get("fact_value")) if new else None,
            old_evidence=(
                str(old.get("observed_evidence") or old.get("evidence_text") or "")
                or None
                if old else None
            ),
            new_evidence=(
                str(new.get("observed_evidence") or new.get("evidence_text") or "")
                or None
                if new else None
            ),
            old_source_url=(
                str(old.get("observed_source_url") or old.get("source_url") or "")
                or None
                if old else None
            ),
            new_source_url=(
                str(new.get("observed_source_url") or new.get("source_url") or "")
                or None
                if new else None
            ),
            confidence=min(confidences) if confidences else None,
            reason=reason,
            detected_at=detected_at,
            run_id=run_id,
        )

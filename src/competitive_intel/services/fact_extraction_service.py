"""Structured fact extraction with deterministic evidence enforcement."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from time import perf_counter

from competitive_intel.domain.evidence import EvidenceChecker
from competitive_intel.domain.fact_comparison import FactNormalizer
from competitive_intel.domain.fact_normalization import normalize_fact
from competitive_intel.domain.fact_schema import REQUIRED
from competitive_intel.domain.facts import (
    CandidateFact, EvidenceCheckStatus, FactCategory, FactExtractionLimits,
    FactExtractionResult, RejectedFact, SavedFact,
)
from competitive_intel.infrastructure.facts.base import (
    FactExtractionProvider, FactExtractionRequest, FactExtractionResponse,
)
from competitive_intel.persistence import Persistence


ALLOWED_BY_SOURCE = {
    "HOMEPAGE": (FactCategory.POSITIONING, FactCategory.FEATURE),
    "FEATURES": (FactCategory.FEATURE, FactCategory.POSITIONING),
    "PRICING": (FactCategory.PLAN, FactCategory.PRICE),
    "CHANGELOG": (FactCategory.PRODUCT_UPDATE, FactCategory.FEATURE),
    "OTHER": (),
}


class FactExtractionService:
    def __init__(
        self,
        persistence: Persistence,
        provider: FactExtractionProvider,
        *,
        evidence_checker: EvidenceChecker | None = None,
        limits: FactExtractionLimits | None = None,
    ) -> None:
        self._persistence = persistence
        self._provider = provider
        self._checker = evidence_checker or EvidenceChecker()
        self._limits = limits or FactExtractionLimits()
        self._history_normalizer = FactNormalizer()

    def extract(
        self,
        competitor_name: str,
        *,
        run_id: int | None = None,
        current_run_only: bool = False,
        source_id: int | None = None,
    ) -> FactExtractionResult:
        warnings: list[str] = []
        errors: list[str] = []
        saved: list[SavedFact] = []
        rejected: list[RejectedFact] = []
        candidate_count = 0
        duplicate_count = 0
        historical_reuse_count = 0
        run_seen_keys: set[tuple[str, str]] = set()
        run_values: dict[tuple[str, str], str] = {}
        normalized_name = competitor_name.strip().casefold()

        with self._persistence.transaction() as session:
            competitor = self._persistence.competitors.get_by_normalized_name(
                session, normalized_name
            )
        if competitor is None:
            return FactExtractionResult(
                competitor_name, None, None, self._provider.name, (), (), 0,
                (), (), 0, 0, (), ("Competitor was not found.",),
            )

        owns_run = run_id is None
        policy_key = getattr(self._provider, "policy_key", None)
        stage_id: int | None = None
        with self._persistence.transaction() as session:
            all_sources = self._persistence.sources.list_verified(
                session, competitor["id"]
            )
            if source_id is not None:
                all_sources = [source for source in all_sources if source["id"] == source_id]
                if not all_sources:
                    raise ValueError("Source must be verified, enabled, and belong to this competitor.")
            sources = all_sources[: self._limits.max_pages]
            if owns_run:
                run_id = self._persistence.agent_runs.create(
                    session,
                    competitor_id=competitor["id"],
                    input_name=competitor_name,
                    normalized_input=normalized_name,
                    run_mode="UNKNOWN",
                    current_state="FACT_EXTRACTION",
                    max_tool_calls=self._limits.max_model_calls,
                )
                stage_id = self._persistence.stage_events.create(
                    session,
                    run_id=run_id,
                    stage="FACT_EXTRACTION",
                    attempt_no=1,
                    max_attempts=1,
                    details={
                        "source_count": len(sources),
                        "provider": self._provider.name,
                    },
                )
        assert run_id is not None
        if len(all_sources) > len(sources):
            warnings.append(
                f"Page limit reached; {len(all_sources) - len(sources)} sources were skipped."
            )
            if policy_key:
                errors.append("PAGE_LIMIT_INCOMPLETE_EXTRACTION")

        source_ids: list[int] = []
        snapshot_ids: list[int] = []
        model_calls = 0
        call_index = 0
        provider_calls: list[dict] = []
        for source in sources:
            source_ids.append(source["id"])
            with self._persistence.transaction() as session:
                snapshot = (
                    self._persistence.snapshots.get_successful_for_source_run(
                        session, source["id"], run_id
                    )
                    if current_run_only
                    else self._persistence.snapshots.get_latest_successful(
                        session, source["id"]
                    )
                )
            if not snapshot or not snapshot["clean_content"]:
                warnings.append(
                    f"Source {source['id']} has no successful clean snapshot; skipped."
                )
                if policy_key:
                    errors.append(f"Source {source['id']}: MISSING_SUCCESSFUL_SNAPSHOT")
                continue
            snapshot_ids.append(snapshot["id"])
            allowed = ALLOWED_BY_SOURCE.get(source["source_type"], ())
            if not allowed:
                warnings.append(f"Source type {source['source_type']} has no fact schema.")
                if policy_key:
                    errors.append(f"Source {source['id']}: NO_PAGE_CONTRACT")
                continue
            if model_calls >= self._limits.max_model_calls:
                warnings.append("Model call limit reached.")
                if policy_key:
                    errors.append("MODEL_CALL_LIMIT_INCOMPLETE_EXTRACTION")
                break
            model_calls += 1
            call_index += 1
            content = snapshot["clean_content"]
            if policy_key and len(content) > self._limits.max_input_characters:
                errors.append(f"Snapshot {snapshot['id']}: INPUT_TOO_LONG_NO_EXTRACTION")
                continue
            provider_content = content[: self._limits.max_input_characters]
            if len(content) > len(provider_content):
                warnings.append(
                    f"Snapshot {snapshot['id']} input was truncated to "
                    f"{self._limits.max_input_characters} characters."
                )
            tool_call_id: int | None = None
            if owns_run:
                with self._persistence.transaction() as session:
                    tool_call_id = self._persistence.tool_calls.create(
                        session,
                        run_id=run_id,
                        stage_event_id=stage_id,
                        call_index=call_index,
                        tool_name="extract_facts",
                        input_summary={
                            "source_id": source["id"],
                            "snapshot_id": snapshot["id"],
                            "provider": self._provider.name,
                            "input_characters": len(provider_content),
                        },
                    )
            started = perf_counter()
            cache_key = sha256(json.dumps([
                "complete-page-v2", source["id"], source["source_type"], policy_key,
                self._limits.max_facts_per_page, content,
            ], ensure_ascii=False).encode()).hexdigest() if policy_key else None
            reused = False
            try:
                response = None
                if cache_key:
                    with self._persistence.transaction() as session:
                        cached = self._persistence.fact_observations.get_cached_page(session, cache_key)
                        origin = self._persistence.snapshots.get(session, cached["snapshot_id"]) if cached else None
                    if (cached and origin and origin["source_id"] == source["id"]
                            and origin["fetch_status"] == "SUCCESS" and origin["clean_content"] == content
                            and cached.get("source_url") == source["url"]):
                        response = FactExtractionResponse(tuple(CandidateFact(
                            FactCategory(row["fact_category"]),
                            row["fact_value"], row["evidence_text"], row["evidence_text"], float(row["confidence"]),
                        ) for row in cached["validated_facts"]), self._provider.name,
                            self._provider.settings.model or "", "", {}, page_status=cached["page_status"])
                        reused = True
                if response is None:
                    response = self._provider.extract(FactExtractionRequest(
                        competitor_name,
                        source["source_type"],
                        source["url"],
                        snapshot["id"],
                        provider_content,
                        allowed,
                        {item.value: REQUIRED[item] for item in allowed},
                        self._limits.max_facts_per_page,
                    ))
            except Exception as exc:
                message = f"Source {source['id']} provider error: {type(exc).__name__}"
                if not policy_key:
                    message += f": {exc}"
                errors.append(message)
                if tool_call_id is not None:
                    self._finish_tool(
                        tool_call_id, "FAILED", perf_counter() - started,
                        0, 0, 0, message,
                    )
                continue
            candidates = response.candidate_facts[: self._limits.max_facts_per_page]
            candidate_count += max(response.returned_fact_count, len(candidates))
            if len(response.candidate_facts) > len(candidates):
                warnings.append(
                    f"Source {source['id']} returned more than "
                    f"{self._limits.max_facts_per_page} facts; extras were ignored."
                )
            warnings.extend(response.warnings)
            audit = {"source_id": source["id"], "snapshot_id": snapshot["id"],
                     "provider": response.provider, "model": response.model,
                     "duration_ms": max(0, int((perf_counter() - started) * 1000)),
                     "usage": response.usage, "attempts": response.attempts,
                     "reused": reused, "candidate_count": len(candidates),
                     "status": "FAILED" if response.error else "SUCCEEDED", "error_code": response.error}
            audit["page_status"] = response.page_status
            audit["source_type"] = source["source_type"]
            audit["returned_fact_count"] = max(response.returned_fact_count, len(candidates))
            audit["fact_rejections"] = [
                {**item, "source_id": source["id"], "snapshot_id": snapshot["id"]}
                for item in response.fact_rejections
            ]
            audit["duplicates"] = list(response.duplicates)
            duplicate_count += len(response.duplicates)
            audit["http_audit"] = list(response.http_audit)
            audit["contract_adaptations"] = [
                {**item, "source_id": source["id"]} for item in response.contract_adaptations
            ]
            audit["evidence_diagnostics"] = [
                {**item, "source_id": source["id"], "snapshot_id": snapshot["id"]}
                for item in response.evidence_diagnostics
            ]
            provider_calls.append(audit)
            if response.error:
                errors.append(f"Source {source['id']}: {response.error}")
            confirmed_for_page = 0
            validated_facts: list[dict] = []
            rejected_for_page = len(response.fact_rejections)
            for item in response.fact_rejections:
                rejected.append(RejectedFact(None,
                    EvidenceCheckStatus.INVALID_SCHEMA if item["error_code"] == "INVALID_SCHEMA"
                    else EvidenceCheckStatus.INSUFFICIENT_EVIDENCE,
                    f"fact[{item['fact_index']}]: {item['error_code']}", source["url"], snapshot["id"]))
            seen_keys: set[str] = set()
            with self._persistence.transaction() as session:
                existing = self._persistence.product_facts.list_for_snapshot(
                    session, snapshot["id"]
                )
            existing_keys = {item["fact_key"] for item in existing}
            for candidate in candidates:
                candidate = replace(
                    candidate,
                    competitor_id=competitor["id"],
                    source_id=source["id"],
                    snapshot_id=snapshot["id"],
                    source_url=source["url"],
                )
                warnings.extend(
                    f"Source {source['id']}: {warning}"
                    for warning in candidate.extraction_warnings
                )
                if candidate.fact_category not in allowed:
                    rejected_for_page += 1
                    rejected.append(
                        RejectedFact(
                            replace(
                                candidate,
                                evidence_status=EvidenceCheckStatus.INVALID_SCHEMA,
                            ),
                            EvidenceCheckStatus.INVALID_SCHEMA,
                            "Fact category is not allowed for this source type.",
                            source["url"],
                            snapshot["id"],
                        )
                    )
                    continue
                check = self._checker.check(
                    candidate, content, source["url"],
                    existing_keys=seen_keys if policy_key else existing_keys | seen_keys,
                )
                if check.status != EvidenceCheckStatus.CONFIRMED:
                    if policy_key and check.status == EvidenceCheckStatus.DUPLICATE:
                        duplicate_count += 1
                        audit["duplicates"].append({"reason": "EXISTING_SNAPSHOT_KEY", "action": "SKIPPED"})
                        continue
                    rejected_for_page += 1
                    if check.status == EvidenceCheckStatus.DUPLICATE:
                        duplicate_count += 1
                    rejected.append(
                        RejectedFact(
                            replace(
                                candidate,
                                fact_key=check.fact_key,
                                evidence_status=check.status,
                            ),
                            check.status, check.reason,
                            source["url"], snapshot["id"],
                        )
                    )
                    continue
                normalized = replace(
                    normalize_fact(candidate),
                    evidence_status=EvidenceCheckStatus.CONFIRMED,
                )
                if policy_key:
                    validated_facts.append({"fact_category": normalized.fact_category.value,
                        "fact_value": normalized.fact_value, "evidence_text": normalized.evidence_text,
                        "confidence": normalized.confidence})
                identity = (
                    normalized.fact_category.value,
                    normalized.fact_key or "",
                )
                if identity in run_seen_keys:
                    if policy_key and run_values[identity] != self._history_normalizer.canonical_json(
                            normalized.fact_category.value, normalized.fact_value):
                        rejected_for_page += 1
                        errors.append(f"Source {source['id']}: CONFLICTING_FACT_IDENTITY")
                        rejected.append(RejectedFact(normalized, EvidenceCheckStatus.CONFLICTING,
                            "Cross-source canonical values conflict.", source["url"], snapshot["id"]))
                        continue
                    duplicate_count += 1
                    rejected.append(
                        RejectedFact(
                            normalized,
                            EvidenceCheckStatus.DUPLICATE,
                            "Fact identity already observed in this extraction run.",
                            source["url"],
                            snapshot["id"],
                        )
                    )
                    continue
                business_value = self._history_normalizer.normalize(
                    normalized.fact_category.value, normalized.fact_value
                )
                canonical = self._history_normalizer.canonical_json(
                    normalized.fact_category.value, normalized.fact_value
                )
                value_hash = sha256(canonical.encode("utf-8")).hexdigest()
                observed_at = datetime.now(UTC).replace(tzinfo=None)
                with self._persistence.transaction() as session:
                    existing_fact = self._persistence.product_facts.find_by_snapshot_key(
                        session, snapshot["id"], normalized.fact_key or ""
                    )
                    if existing_fact and not policy_key:
                        duplicate_count += 1
                        rejected.append(
                            RejectedFact(
                                normalized, EvidenceCheckStatus.DUPLICATE,
                                "Fact already persisted for this snapshot.",
                                source["url"], snapshot["id"],
                            )
                        )
                        continue
                    current_fact = self._persistence.fact_versions.find_current(
                        session,
                        competitor["id"],
                        normalized.fact_category.value,
                        normalized.fact_key or "",
                    )
                    latest_fact = current_fact or (
                        self._persistence.fact_versions.find_latest(
                            session,
                            competitor["id"],
                            normalized.fact_category.value,
                            normalized.fact_key or "",
                        )
                    )
                    if existing_fact and policy_key:
                        if (existing_fact["evidence_status"] != "CONFIRMED" or
                                self._history_normalizer.canonical_json(normalized.fact_category.value,
                                    existing_fact["fact_value"]) != canonical):
                            errors.append(f"Source {source['id']}: EXISTING_SNAPSHOT_VALUE_CONFLICT")
                            rejected_for_page += 1
                            continue
                        fact_id = int(existing_fact["id"])
                        historical_reuse_count += 1
                        duplicate_count += 1
                        audit["duplicates"].append({"reason": "EXISTING_SNAPSHOT_KEY", "action": "OBSERVED"})
                    elif (
                        current_fact
                        and (not policy_key or reused)
                        and (
                            current_fact["normalized_value_hash"] == value_hash
                            or self._history_normalizer.canonical_json(
                                normalized.fact_category.value,
                                current_fact["normalized_value"],
                            )
                            == canonical
                        )
                    ):
                        fact_id = int(current_fact["id"])
                        historical_reuse_count += 1
                    else:
                        fact_id = self._persistence.product_facts.create(
                            session,
                            competitor_id=competitor["id"],
                            run_id=run_id,
                            snapshot_id=snapshot["id"],
                            fact_category=normalized.fact_category.value,
                            fact_key=normalized.fact_key or "",
                            fact_value=normalized.fact_value,
                            value_text=normalized.value_text,
                            statement_type="FACT",
                            source_url=source["url"],
                            evidence_text=normalized.evidence_text,
                            confidence=normalized.confidence,
                            evidence_status="CONFIRMED",
                            extracted_at=observed_at,
                        )
                        self._persistence.fact_versions.create(
                            session,
                            fact_id=fact_id,
                            competitor_id=competitor["id"],
                            source_id=source["id"],
                            normalized_value=business_value,
                            normalized_value_hash=value_hash,
                            valid_from=observed_at,
                            supersedes_fact_id=(
                                int(latest_fact["id"]) if latest_fact else None
                            ),
                        )
                    _, observation_created = (
                        self._persistence.fact_observations.create_idempotent(
                            session,
                            competitor_id=competitor["id"],
                            run_id=run_id,
                            fact_id=fact_id,
                            source_id=source["id"],
                            snapshot_id=snapshot["id"],
                            evidence_text=normalized.evidence_text,
                            confidence=normalized.confidence,
                            observed_at=observed_at,
                        )
                    )
                    if not observation_created:
                        duplicate_count += 1
                        continue
                run_seen_keys.add(identity)
                run_values[identity] = canonical
                seen_keys.add(normalized.fact_key or "")
                existing_keys.add(normalized.fact_key or "")
                confirmed_for_page += 1
                saved.append(
                    SavedFact(
                        fact_id=fact_id,
                        source_id=source["id"],
                        snapshot_id=snapshot["id"],
                        category=normalized.fact_category,
                        fact_key=normalized.fact_key or "",
                        fact_value=normalized.fact_value,
                        evidence_text=normalized.evidence_text,
                        source_url=source["url"],
                        confidence=normalized.confidence,
                        extraction_warnings=normalized.extraction_warnings,
                    )
                )
            audit["confirmed_count"] = confirmed_for_page
            audit["rejected_count"] = rejected_for_page
            if rejected_for_page:
                audit["page_status"] = "PARTIAL_ERROR" if confirmed_for_page else "FAILED"
            if cache_key and not response.error and not rejected_for_page:
                audit["cache_key"] = cache_key
                audit["cache_version"] = 2
                audit["source_url"] = source["url"]
                audit["validated_facts"] = validated_facts
            if policy_key and rejected_for_page and not response.error:
                errors.append(f"Source {source['id']}: EVIDENCE_REJECTED")
            if tool_call_id is not None:
                self._finish_tool(
                    tool_call_id,
                    "FAILED" if response.error else "SUCCEEDED",
                    perf_counter() - started,
                    len(candidates), confirmed_for_page, rejected_for_page,
                    response.error,
                    audit,
                )

        if owns_run:
            assert stage_id is not None
            with self._persistence.transaction() as session:
                for fact in ([] if errors and policy_key else self._persistence.fact_observations.list_for_run(
                    session, run_id
                )):
                    self._persistence.fact_versions.activate(
                        session, fact["id"], "BASELINE"
                    )
                    self._persistence.fact_observations.update_status(
                        session, run_id, fact["id"], "BASELINE"
                    )
                self._persistence.stage_events.finish(
                    session, stage_id, status="FAILED" if errors and policy_key else "SUCCEEDED"
                )
                self._persistence.agent_runs.finish(
                    session, run_id, status="FAILED" if errors and policy_key else "COMPLETED",
                    current_state="FAILED" if errors and policy_key else "COMPLETED"
                )
        return FactExtractionResult(
            competitor_name, competitor["id"], run_id, self._provider.name,
            tuple(source_ids), tuple(snapshot_ids), candidate_count, tuple(saved),
            tuple(rejected), duplicate_count, historical_reuse_count,
            tuple(warnings), tuple(errors), tuple(provider_calls),
        )

    def _finish_tool(
        self,
        tool_call_id: int,
        status: str,
        elapsed: float,
        candidates: int,
        confirmed: int,
        rejected: int,
        error: str | None,
        audit: dict | None = None,
    ) -> None:
        with self._persistence.transaction() as session:
            self._persistence.tool_calls.finish(
                session,
                tool_call_id,
                status=status,
                output_summary={
                    "candidate_count": candidates,
                    "confirmed_count": confirmed,
                    "rejected_count": rejected,
                    "provider_calls": [audit] if audit else [],
                },
                duration_ms=max(0, int(elapsed * 1000)),
                error_code="PROVIDER_ERROR" if error else None,
                error_message=error,
            )

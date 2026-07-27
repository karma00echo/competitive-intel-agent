"""Structured fact extraction with deterministic evidence enforcement."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from time import perf_counter

from competitive_intel.domain.evidence import EvidenceChecker
from competitive_intel.domain.fact_normalization import normalize_fact
from competitive_intel.domain.fact_schema import REQUIRED
from competitive_intel.domain.facts import (
    EvidenceCheckStatus, FactCategory, FactExtractionLimits,
    FactExtractionResult, RejectedFact, SavedFact,
)
from competitive_intel.infrastructure.facts.base import (
    FactExtractionProvider, FactExtractionRequest,
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

    def extract(
        self,
        competitor_name: str,
        *,
        run_id: int | None = None,
        current_run_only: bool = False,
    ) -> FactExtractionResult:
        warnings: list[str] = []
        errors: list[str] = []
        saved: list[SavedFact] = []
        rejected: list[RejectedFact] = []
        candidate_count = 0
        duplicate_count = 0
        normalized_name = competitor_name.strip().casefold()

        with self._persistence.transaction() as session:
            competitor = self._persistence.competitors.get_by_normalized_name(
                session, normalized_name
            )
        if competitor is None:
            return FactExtractionResult(
                competitor_name, None, None, self._provider.name, (), (), 0,
                (), (), 0, (), ("Competitor was not found.",),
            )

        owns_run = run_id is None
        stage_id: int | None = None
        with self._persistence.transaction() as session:
            all_sources = self._persistence.sources.list_verified(
                session, competitor["id"]
            )
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

        source_ids: list[int] = []
        snapshot_ids: list[int] = []
        model_calls = 0
        call_index = 0
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
                continue
            snapshot_ids.append(snapshot["id"])
            allowed = ALLOWED_BY_SOURCE.get(source["source_type"], ())
            if not allowed:
                warnings.append(f"Source type {source['source_type']} has no fact schema.")
                continue
            if model_calls >= self._limits.max_model_calls:
                warnings.append("Model call limit reached.")
                break
            model_calls += 1
            call_index += 1
            content = snapshot["clean_content"]
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
            try:
                response = self._provider.extract(
                    FactExtractionRequest(
                        competitor_name,
                        source["source_type"],
                        source["url"],
                        snapshot["id"],
                        provider_content,
                        allowed,
                        {item.value: REQUIRED[item] for item in allowed},
                        self._limits.max_facts_per_page,
                    )
                )
            except Exception as exc:
                message = f"Source {source['id']} provider error: {type(exc).__name__}: {exc}"
                errors.append(message)
                if tool_call_id is not None:
                    self._finish_tool(
                        tool_call_id, "FAILED", perf_counter() - started,
                        0, 0, 0, message,
                    )
                continue
            candidates = response.candidate_facts[: self._limits.max_facts_per_page]
            candidate_count += len(candidates)
            if len(response.candidate_facts) > len(candidates):
                warnings.append(
                    f"Source {source['id']} returned more than "
                    f"{self._limits.max_facts_per_page} facts; extras were ignored."
                )
            warnings.extend(response.warnings)
            if response.error:
                errors.append(f"Source {source['id']}: {response.error}")
            confirmed_for_page = 0
            rejected_for_page = 0
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
                    existing_keys=existing_keys | seen_keys,
                )
                if check.status != EvidenceCheckStatus.CONFIRMED:
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
                with self._persistence.transaction() as session:
                    existing_fact = self._persistence.product_facts.find_by_snapshot_key(
                        session, snapshot["id"], normalized.fact_key or ""
                    )
                    if existing_fact:
                        duplicate_count += 1
                        rejected.append(
                            RejectedFact(
                                normalized, EvidenceCheckStatus.DUPLICATE,
                                "Fact already persisted for this snapshot.",
                                source["url"], snapshot["id"],
                            )
                        )
                        continue
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
                        extracted_at=datetime.now(UTC).replace(tzinfo=None),
                    )
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
            if tool_call_id is not None:
                self._finish_tool(
                    tool_call_id,
                    "FAILED" if response.error else "SUCCEEDED",
                    perf_counter() - started,
                    len(candidates), confirmed_for_page, rejected_for_page,
                    response.error,
                )

        if owns_run:
            assert stage_id is not None
            with self._persistence.transaction() as session:
                self._persistence.stage_events.finish(
                    session, stage_id, status="SUCCEEDED"
                )
                self._persistence.agent_runs.finish(
                    session, run_id, status="COMPLETED", current_state="COMPLETED"
                )
        return FactExtractionResult(
            competitor_name, competitor["id"], run_id, self._provider.name,
            tuple(source_ids), tuple(snapshot_ids), candidate_count, tuple(saved),
            tuple(rejected), duplicate_count, tuple(warnings), tuple(errors),
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
                },
                duration_ms=max(0, int(elapsed * 1000)),
                error_code="PROVIDER_ERROR" if error else None,
                error_message=error,
            )

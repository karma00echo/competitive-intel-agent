"""Application service for baseline selection and deterministic change persistence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from competitive_intel.domain.fact_comparison import (
    ChangeType,
    FactComparisonResult,
    FactComparisonService,
)
from competitive_intel.persistence import Persistence


@dataclass(frozen=True, slots=True)
class PreviousFactBaseline:
    previous_successful_run_id: int | None
    previous_fact_count: int
    current_fact_count: int
    comparable_source_count: int
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PersistedComparison:
    result: FactComparisonResult
    change_ids: tuple[int, ...]


class FactHistoryService:
    def __init__(
        self,
        persistence: Persistence,
        comparison: FactComparisonService | None = None,
    ) -> None:
        self._persistence = persistence
        self._comparison = comparison or FactComparisonService()

    def get_previous_baseline(
        self, competitor_id: int, current_run_id: int
    ) -> PreviousFactBaseline:
        with self._persistence.transaction() as session:
            previous = (
                self._persistence.agent_runs.get_previous_successful_with_facts(
                    session, competitor_id, current_run_id
                )
            )
            current_facts = self._persistence.fact_observations.list_for_run(
                session, current_run_id
            )
            previous_facts = (
                self._persistence.fact_observations.list_for_run(
                    session, previous["id"]
                )
                if previous else []
            )
            snapshots = self._persistence.snapshots.list_for_run(
                session, current_run_id
            )
        comparable_sources = {
            int(item["source_id"])
            for item in snapshots
            if item["fetch_status"] == "SUCCESS"
        }
        warnings = (
            ()
            if previous
            else ("No previous successful run with facts was found.",)
        )
        return PreviousFactBaseline(
            int(previous["id"]) if previous else None,
            len(previous_facts),
            len(current_facts),
            len(comparable_sources),
            warnings,
        )

    def establish_baseline(
        self, competitor_id: int, current_run_id: int
    ) -> int:
        now = datetime.now(UTC).replace(tzinfo=None)
        with self._persistence.transaction() as session:
            facts = self._persistence.fact_observations.list_for_run(
                session, current_run_id
            )
            observed_ids = {int(fact["id"]) for fact in facts}
            for current in self._persistence.fact_versions.list_current(
                session, competitor_id
            ):
                if int(current["id"]) not in observed_ids:
                    self._persistence.fact_versions.close(
                        session, current["id"], now, "BASELINE"
                    )
            for fact in facts:
                self._persistence.fact_versions.activate(
                    session, fact["id"], "BASELINE"
                )
                self._persistence.fact_observations.update_status(
                    session, current_run_id, fact["id"], "BASELINE"
                )
        return len(facts)

    def compare_and_persist(
        self,
        competitor_id: int,
        current_run_id: int,
        previous_successful_run_id: int,
    ) -> PersistedComparison:
        with self._persistence.transaction() as session:
            current = self._persistence.fact_observations.list_for_run(
                session, current_run_id
            )
            previous = self._persistence.fact_observations.list_for_run(
                session, previous_successful_run_id
            )
            snapshots = self._persistence.snapshots.list_for_run(
                session, current_run_id
            )
        observed_source_ids = {int(item["source_id"]) for item in current}
        coverage = {
            int(item["source_id"]): (
                item["fetch_status"] == "SUCCESS"
                and int(item["source_id"]) in observed_source_ids
            )
            for item in snapshots
        }
        result = self._comparison.compare(
            competitor_id=competitor_id,
            current_run_id=current_run_id,
            previous_successful_run_id=previous_successful_run_id,
            current_facts=current,
            previous_facts=previous,
            source_fetch_results=coverage,
            comparison_policy={"warnings_are_valid_baselines": True},
        )
        now = datetime.now(UTC).replace(tzinfo=None)
        change_ids: list[int] = []
        with self._persistence.transaction() as session:
            for change in result.all_changes:
                logical = change.change_type.value
                physical = (
                    "UNKNOWN"
                    if change.change_type == ChangeType.UNCOMPARABLE
                    else logical
                )
                change_id = self._persistence.changes.create_idempotent(
                    session,
                    competitor_id=competitor_id,
                    run_id=current_run_id,
                    change_type=physical,
                    fact_key=change.fact_key,
                    old_fact_id=change.old_fact_id,
                    new_fact_id=change.new_fact_id,
                    old_value=change.old_value,
                    new_value=change.new_value,
                    evidence_text=change.new_evidence or change.old_evidence,
                    impact_assessment=change.reason,
                    confidence=change.confidence,
                    verification_status=(
                        "PENDING"
                        if change.change_type == ChangeType.UNCOMPARABLE
                        else "CONFIRMED"
                    ),
                )
                change_ids.append(change_id)
                if change.new_fact_id is not None:
                    self._persistence.fact_observations.update_status(
                        session,
                        current_run_id,
                        change.new_fact_id,
                        logical,
                    )
                if change.change_type == ChangeType.ADDED:
                    assert change.new_fact_id is not None
                    self._persistence.fact_versions.activate(
                        session, change.new_fact_id, logical
                    )
                elif change.change_type == ChangeType.MODIFIED:
                    assert change.old_fact_id is not None
                    assert change.new_fact_id is not None
                    self._persistence.fact_versions.close(
                        session, change.old_fact_id, now, logical
                    )
                    self._persistence.fact_versions.activate(
                        session, change.new_fact_id, logical
                    )
                elif change.change_type == ChangeType.UNCHANGED:
                    assert change.new_fact_id is not None
                    if (
                        change.old_fact_id is not None
                        and change.old_fact_id != change.new_fact_id
                    ):
                        self._persistence.fact_versions.close(
                            session, change.old_fact_id, now, logical
                        )
                    self._persistence.fact_versions.activate(
                        session, change.new_fact_id, logical
                    )
                elif change.change_type == ChangeType.REMOVED:
                    assert change.old_fact_id is not None
                    self._persistence.fact_versions.close(
                        session, change.old_fact_id, now, logical
                    )
                # UNCOMPARABLE intentionally preserves the previous current fact.
        return PersistedComparison(result, tuple(change_ids))

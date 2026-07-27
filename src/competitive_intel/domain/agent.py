"""Controlled single-agent state, tool, and run-summary contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class AgentState(StrEnum):
    INITIALIZING = "INITIALIZING"
    PROFILE_LOOKUP = "PROFILE_LOOKUP"
    MODE_SELECTION = "MODE_SELECTION"
    SOURCE_DISCOVERY = "SOURCE_DISCOVERY"
    SOURCE_VALIDATION = "SOURCE_VALIDATION"
    PAGE_FETCHING = "PAGE_FETCHING"
    SNAPSHOT_PERSISTENCE = "SNAPSHOT_PERSISTENCE"
    FACT_EXTRACTION = "FACT_EXTRACTION"
    FACT_PERSISTENCE = "FACT_PERSISTENCE"
    HISTORY_LOOKUP = "HISTORY_LOOKUP"
    FACT_COMPARISON = "FACT_COMPARISON"
    CHANGE_PERSISTENCE = "CHANGE_PERSISTENCE"
    REPORT_GENERATION = "REPORT_GENERATION"
    REPORT_PERSISTENCE = "REPORT_PERSISTENCE"
    RUN_SUMMARY = "RUN_SUMMARY"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_WARNINGS = "COMPLETED_WITH_WARNINGS"
    FAILED = "FAILED"


class RunMode(StrEnum):
    BASELINE = "BASELINE"
    REFRESH = "REFRESH"


TERMINAL_STATES = {
    AgentState.COMPLETED,
    AgentState.COMPLETED_WITH_WARNINGS,
    AgentState.FAILED,
}


ALLOWED_TRANSITIONS: dict[AgentState, frozenset[AgentState]] = {
    AgentState.INITIALIZING: frozenset(
        {AgentState.PROFILE_LOOKUP, AgentState.FAILED}
    ),
    AgentState.PROFILE_LOOKUP: frozenset(
        {AgentState.MODE_SELECTION, AgentState.FAILED}
    ),
    AgentState.MODE_SELECTION: frozenset(
        {
            AgentState.SOURCE_DISCOVERY,
            AgentState.PAGE_FETCHING,
            AgentState.FAILED,
        }
    ),
    AgentState.SOURCE_DISCOVERY: frozenset(
        {AgentState.SOURCE_VALIDATION, AgentState.FAILED}
    ),
    AgentState.SOURCE_VALIDATION: frozenset(
        {AgentState.PAGE_FETCHING, AgentState.FAILED}
    ),
    AgentState.PAGE_FETCHING: frozenset(
        {AgentState.SNAPSHOT_PERSISTENCE, AgentState.FAILED}
    ),
    AgentState.SNAPSHOT_PERSISTENCE: frozenset(
        {AgentState.FACT_EXTRACTION, AgentState.FAILED}
    ),
    AgentState.FACT_EXTRACTION: frozenset(
        {AgentState.FACT_PERSISTENCE, AgentState.FAILED}
    ),
    AgentState.FACT_PERSISTENCE: frozenset(
        {
            AgentState.HISTORY_LOOKUP,
            AgentState.REPORT_GENERATION,
            AgentState.FAILED,
        }
    ),
    AgentState.HISTORY_LOOKUP: frozenset(
        {AgentState.FACT_COMPARISON, AgentState.FAILED}
    ),
    AgentState.FACT_COMPARISON: frozenset(
        {AgentState.CHANGE_PERSISTENCE, AgentState.FAILED}
    ),
    AgentState.CHANGE_PERSISTENCE: frozenset(
        {AgentState.REPORT_GENERATION, AgentState.FAILED}
    ),
    AgentState.REPORT_GENERATION: frozenset(
        {AgentState.REPORT_PERSISTENCE, AgentState.FAILED}
    ),
    AgentState.REPORT_PERSISTENCE: frozenset(
        {AgentState.RUN_SUMMARY, AgentState.FAILED}
    ),
    AgentState.RUN_SUMMARY: frozenset(
        {
            AgentState.COMPLETED,
            AgentState.COMPLETED_WITH_WARNINGS,
            AgentState.FAILED,
        }
    ),
    AgentState.COMPLETED: frozenset(),
    AgentState.COMPLETED_WITH_WARNINGS: frozenset(),
    AgentState.FAILED: frozenset(),
}


class InvalidStateTransition(ValueError):
    pass


def validate_transition(current: AgentState, target: AgentState) -> None:
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvalidStateTransition(
            f"Illegal state transition: {current.value} -> {target.value}"
        )


@dataclass(frozen=True, slots=True)
class ToolResult:
    ok: bool
    data: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class AgentRunSummary:
    run_id: int
    competitor_name: str
    normalized_name: str
    run_mode: RunMode
    final_state: AgentState
    official_homepage: str | None
    verified_source_count: int
    page_fetch_success_count: int
    page_fetch_failure_count: int
    baseline_page_count: int
    unchanged_page_count: int
    changed_page_count: int
    confirmed_fact_count: int
    rejected_fact_count: int
    duplicate_fact_count: int
    tool_call_count: int
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    report_id: int | None = None
    report_type: str | None = None
    added_count: int = 0
    removed_count: int = 0
    modified_count: int = 0
    unchanged_count: int = 0
    uncomparable_count: int = 0
    historical_reuse_count: int = 0


@dataclass(frozen=True, slots=True)
class AgentRunnerLimits:
    max_tool_calls: int = 12
    max_provider_calls_per_state: int = 2
    max_duplicate_attempts: int = 2
    max_context_messages: int = 20


@dataclass(frozen=True, slots=True)
class AgentRunResult:
    run_id: int
    run_mode: RunMode | None
    final_state: AgentState
    summary: AgentRunSummary | None
    tool_call_count: int
    transitions: tuple[tuple[AgentState, AgentState], ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(slots=True)
class ControlledRunContext:
    run_id: int
    competitor_name: str
    normalized_name: str
    current_state: AgentState
    max_tool_calls: int
    competitor_id: int | None = None
    run_mode: RunMode | None = None
    completed_states: list[AgentState] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    tool_results: dict[str, ToolResult] = field(default_factory=dict)
    transitions: list[tuple[AgentState, AgentState]] = field(default_factory=list)
    summary: AgentRunSummary | None = None
    previous_successful_run_id: int | None = None
    tool_call_count: int = 0
    persisted_stage_attempts: dict[str, int] = field(default_factory=dict)

    @property
    def remaining_tool_budget(self) -> int:
        return max(0, self.max_tool_calls - self.tool_call_count)

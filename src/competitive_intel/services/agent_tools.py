"""Strict, bounded Agent tools that reuse existing services and Persistence."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable

from competitive_intel.domain.agent import (
    AgentRunSummary,
    AgentState,
    ControlledRunContext,
    RunMode,
    ToolResult,
)
from competitive_intel.domain.webpage import PageChangeStatus
from competitive_intel.persistence import Persistence

from .fact_extraction_service import FactExtractionService
from .snapshot_service import SnapshotService
from .source_discovery_service import SourceDiscoveryService


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    states: frozenset[AgentState]

    def provider_schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


def _object_schema(
    properties: dict[str, dict[str, Any]], required: tuple[str, ...] = ()
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


STATUS_STATES = frozenset(
    {
        AgentState.PROFILE_LOOKUP,
        AgentState.SOURCE_DISCOVERY,
        AgentState.PAGE_FETCHING,
        AgentState.FACT_EXTRACTION,
        AgentState.RUN_SUMMARY,
    }
)


TOOL_DEFINITIONS = {
    "get_competitor_profile": ToolDefinition(
        "get_competitor_profile",
        "Read persisted competitor profile completeness.",
        _object_schema(
            {"competitor_name": {"type": "string", "minLength": 1}},
            ("competitor_name",),
        ),
        frozenset({AgentState.PROFILE_LOOKUP}),
    ),
    "discover_competitor_sources": ToolDefinition(
        "discover_competitor_sources",
        "Discover and validate official sources using SourceDiscoveryService.",
        _object_schema(
            {
                "competitor_name": {"type": "string", "minLength": 1},
                "locale": {"type": "string", "minLength": 1},
                "language": {"type": ["string", "null"]},
            },
            ("competitor_name", "locale", "language"),
        ),
        frozenset({AgentState.SOURCE_DISCOVERY}),
    ),
    "refresh_verified_sources": ToolDefinition(
        "refresh_verified_sources",
        "Fetch and persist all active VERIFIED sources.",
        _object_schema(
            {"competitor_name": {"type": "string", "minLength": 1}},
            ("competitor_name",),
        ),
        frozenset({AgentState.PAGE_FETCHING}),
    ),
    "extract_competitor_facts": ToolDefinition(
        "extract_competitor_facts",
        "Extract evidence-bound facts from this run's successful snapshots.",
        _object_schema(
            {"competitor_name": {"type": "string", "minLength": 1}},
            ("competitor_name",),
        ),
        frozenset({AgentState.FACT_EXTRACTION}),
    ),
    "get_run_status": ToolDefinition(
        "get_run_status",
        "Return bounded current runner state and budget.",
        _object_schema({}),
        STATUS_STATES,
    ),
    "finalize_run_summary": ToolDefinition(
        "finalize_run_summary",
        "Build deterministic statistics from this run's persisted records.",
        _object_schema({}),
        frozenset({AgentState.RUN_SUMMARY}),
    ),
}


def validate_tool_arguments(
    schema: dict[str, Any], arguments: dict[str, Any]
) -> tuple[bool, str | None]:
    if not isinstance(arguments, dict):
        return False, "Tool arguments must be an object."
    properties = schema["properties"]
    unknown = set(arguments) - set(properties)
    if unknown:
        return False, f"Unknown arguments: {', '.join(sorted(unknown))}"
    missing = set(schema.get("required", ())) - set(arguments)
    if missing:
        return False, f"Missing arguments: {', '.join(sorted(missing))}"
    for name, value in arguments.items():
        expected = properties[name].get("type")
        accepted = expected if isinstance(expected, list) else [expected]
        type_ok = (
            ("null" in accepted and value is None)
            or ("string" in accepted and isinstance(value, str))
            or ("integer" in accepted and isinstance(value, int) and not isinstance(value, bool))
            or ("boolean" in accepted and isinstance(value, bool))
        )
        if not type_ok:
            return False, f"Argument {name!r} has an invalid type."
        minimum = properties[name].get("minLength")
        if minimum and isinstance(value, str) and len(value.strip()) < minimum:
            return False, f"Argument {name!r} must not be empty."
    return True, None


class AgentToolExecutor:
    def __init__(
        self,
        persistence: Persistence,
        source_discovery: SourceDiscoveryService,
        snapshots: SnapshotService,
        facts: FactExtractionService,
    ) -> None:
        self._persistence = persistence
        self._source_discovery = source_discovery
        self._snapshots = snapshots
        self._facts = facts
        self._handlers: dict[
            str, Callable[[dict[str, Any], ControlledRunContext], ToolResult]
        ] = {
            "get_competitor_profile": self._get_profile,
            "discover_competitor_sources": self._discover_sources,
            "refresh_verified_sources": self._refresh_sources,
            "extract_competitor_facts": self._extract_facts,
            "get_run_status": self._get_run_status,
            "finalize_run_summary": self._finalize_summary,
        }

    def allowed_tools(self, state: AgentState) -> tuple[str, ...]:
        return tuple(
            name for name, definition in TOOL_DEFINITIONS.items()
            if state in definition.states
        )

    def schemas_for(self, names: tuple[str, ...]) -> tuple[dict[str, Any], ...]:
        return tuple(TOOL_DEFINITIONS[name].provider_schema() for name in names)

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        context: ControlledRunContext,
    ) -> ToolResult:
        try:
            return self._handlers[name](arguments, context)
        except Exception as exc:
            return ToolResult(
                False,
                error_code="TOOL_EXECUTION_ERROR",
                error_message=f"{type(exc).__name__}: {exc}"[:500],
                retryable=False,
            )

    def _get_profile(
        self, arguments: dict[str, Any], context: ControlledRunContext
    ) -> ToolResult:
        normalized = arguments["competitor_name"].strip().casefold()
        with self._persistence.transaction() as session:
            competitor = self._persistence.competitors.get_by_normalized_name(
                session, normalized
            )
            if competitor is None:
                return ToolResult(
                    True,
                    {
                        "exists": False,
                        "competitor_id": None,
                        "normalized_name": normalized,
                        "verified_source_count": 0,
                        "successful_snapshot_count": 0,
                        "confirmed_fact_count": 0,
                        "recent_run_status": None,
                    },
                )
            sources = self._persistence.sources.list_verified(
                session, competitor["id"]
            )
            snapshots = (
                self._persistence.snapshots.count_latest_successful_for_competitor(
                    session, competitor["id"]
                )
            )
            facts = self._persistence.product_facts.count_confirmed_for_competitor(
                session, competitor["id"]
            )
            latest = self._persistence.agent_runs.get_latest_for_competitor(
                session, competitor["id"]
            )
        return ToolResult(
            True,
            {
                "exists": True,
                "competitor_id": competitor["id"],
                "normalized_name": competitor["normalized_name"],
                "verified_source_count": len(sources),
                "successful_snapshot_count": snapshots,
                "confirmed_fact_count": facts,
                "recent_run_status": latest["status"] if latest else None,
            },
        )

    def _discover_sources(
        self, arguments: dict[str, Any], context: ControlledRunContext
    ) -> ToolResult:
        result = self._source_discovery.discover(
            arguments["competitor_name"],
            locale=arguments["locale"],
            language=arguments["language"],
        )
        with self._persistence.transaction() as session:
            competitor = self._persistence.competitors.get_by_normalized_name(
                session, result.identity.normalized_name
            )
            verified = (
                self._persistence.sources.list_verified(
                    session, competitor["id"]
                )
                if competitor else []
            )
        return ToolResult(
            bool(verified),
            {
                "competitor_id": competitor["id"] if competitor else None,
                "official_domain": result.official_domain,
                "verified_count": len(verified),
                "verified_sources": [
                    {
                        "id": item["id"],
                        "type": item["source_type"],
                        "url": item["url"],
                    }
                    for item in verified[:10]
                ],
                "pending_count": len(result.pending),
                "rejected_count": len(result.rejected),
                "warnings": list(result.warnings[:20]),
                "errors": list(result.errors[:20]),
            },
            error_code=None if verified else "NO_VERIFIED_OFFICIAL_SOURCE",
            error_message=None if verified else "No VERIFIED official source was found.",
            retryable=False,
        )

    def _refresh_sources(
        self, arguments: dict[str, Any], context: ControlledRunContext
    ) -> ToolResult:
        with self._persistence.transaction() as session:
            competitor = self._persistence.competitors.get_by_normalized_name(
                session, context.normalized_name
            )
            sources = (
                self._persistence.sources.list_verified(
                    session, competitor["id"]
                )
                if competitor else []
            )
        if not sources:
            return ToolResult(
                False,
                error_code="NO_VERIFIED_SOURCES",
                error_message="Competitor has no active VERIFIED sources.",
                retryable=False,
            )
        pages = []
        for source in sources:
            result = self._snapshots.process(
                source_id=source["id"], run_id=context.run_id
            )
            pages.append(
                {
                    "source_id": result.source_id,
                    "snapshot_id": result.snapshot_id,
                    "source_type": source["source_type"],
                    "url": source["url"],
                    "page_status": result.page_status.value,
                    "fetch_status": result.fetch_status.value,
                    "error_code": result.error_code,
                    "error_message": (result.error_message or "")[:240] or None,
                }
            )
        success_count = sum(
            item["fetch_status"] == "SUCCESS" for item in pages
        )
        failures = len(pages) - success_count
        return ToolResult(
            success_count > 0,
            {
                "pages": pages[:20],
                "source_count": len(sources),
                "success_count": success_count,
                "failure_count": failures,
                "warnings": (
                    [f"{failures} verified source pages could not be fetched."]
                    if failures else []
                ),
                "errors": [],
            },
            error_code=None if success_count else "ALL_PAGE_FETCHES_FAILED",
            error_message=None if success_count else "No verified page was fetched successfully.",
            retryable=False,
        )

    def _extract_facts(
        self, arguments: dict[str, Any], context: ControlledRunContext
    ) -> ToolResult:
        result = self._facts.extract(
            arguments["competitor_name"],
            run_id=context.run_id,
            current_run_only=True,
        )
        confirmed = [
            {
                "fact_id": item.fact_id,
                "category": item.category.value,
                "fact_key": item.fact_key,
                "value": item.fact_value,
                "source_url": item.source_url,
                "evidence": item.evidence_text[:240],
                "confidence": item.confidence,
            }
            for item in result.saved[:50]
        ]
        rejected = [
            {
                "status": item.status.value,
                "reason": item.reason[:240],
                "source_url": item.source_url,
                "snapshot_id": item.snapshot_id,
            }
            for item in result.rejected[:50]
        ]
        return ToolResult(
            bool(result.saved),
            {
                "candidate_count": result.candidate_count,
                "confirmed_count": len(result.saved),
                "rejected_count": len(result.rejected),
                "duplicate_count": result.duplicate_count,
                "confirmed": confirmed,
                "rejected": rejected,
                "warnings": list(result.warnings[:20]),
                "errors": list(result.errors[:20]),
            },
            error_code=None if result.saved else "NO_CONFIRMED_FACTS",
            error_message=None if result.saved else "No current facts passed evidence validation.",
            retryable=False,
        )

    def _get_run_status(
        self, arguments: dict[str, Any], context: ControlledRunContext
    ) -> ToolResult:
        return ToolResult(
            True,
            {
                "run_id": context.run_id,
                "run_mode": context.run_mode.value if context.run_mode else None,
                "current_state": context.current_state.value,
                "completed_states": [
                    item.value for item in context.completed_states[-20:]
                ],
                "remaining_tool_budget": context.remaining_tool_budget,
                "warnings": context.warnings[-20:],
                "errors": context.errors[-20:],
            },
        )

    def _finalize_summary(
        self, arguments: dict[str, Any], context: ControlledRunContext
    ) -> ToolResult:
        with self._persistence.transaction() as session:
            competitor = (
                self._persistence.competitors.get(
                    session, context.competitor_id
                )
                if context.competitor_id else None
            )
            sources = (
                self._persistence.sources.list_verified(
                    session, context.competitor_id
                )
                if context.competitor_id else []
            )
            snapshots = self._persistence.snapshots.list_for_run(
                session, context.run_id
            )
            facts = self._persistence.product_facts.list_for_run(
                session, context.run_id
            )
        page_data = context.tool_results.get(
            "refresh_verified_sources", ToolResult(True)
        ).data.get("pages", [])
        fact_data = context.tool_results.get(
            "extract_competitor_facts", ToolResult(True)
        ).data
        official = next(
            (
                item["normalized_url"] for item in sources
                if item["source_type"] == "HOMEPAGE"
            ),
            None,
        )
        statuses = [item.get("page_status") for item in page_data]
        final_state = (
            AgentState.COMPLETED_WITH_WARNINGS
            if context.warnings or context.errors else AgentState.COMPLETED
        )
        summary = AgentRunSummary(
            run_id=context.run_id,
            competitor_name=(
                competitor["canonical_name"] if competitor
                else context.competitor_name
            ),
            normalized_name=context.normalized_name,
            run_mode=context.run_mode or RunMode.BASELINE,
            final_state=final_state,
            official_homepage=official,
            verified_source_count=len(sources),
            page_fetch_success_count=sum(
                item["fetch_status"] == "SUCCESS" for item in snapshots
            ),
            page_fetch_failure_count=sum(
                item["fetch_status"] != "SUCCESS" for item in snapshots
            ),
            baseline_page_count=statuses.count(PageChangeStatus.BASELINE.value),
            unchanged_page_count=statuses.count(PageChangeStatus.UNCHANGED.value),
            changed_page_count=statuses.count(PageChangeStatus.PAGE_CHANGED.value),
            confirmed_fact_count=sum(
                item["evidence_status"] == "CONFIRMED" for item in facts
            ),
            rejected_fact_count=int(fact_data.get("rejected_count", 0)),
            duplicate_fact_count=int(fact_data.get("duplicate_count", 0)),
            tool_call_count=context.tool_call_count,
            warnings=tuple(context.warnings[-50:]),
            errors=tuple(context.errors[-50:]),
        )
        context.summary = summary
        return ToolResult(True, {"summary": asdict(summary)})

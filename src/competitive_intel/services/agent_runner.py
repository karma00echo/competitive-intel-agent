"""Program-controlled single Agent Runner with bounded native tool calling."""

from __future__ import annotations

import json
from collections import Counter
from time import perf_counter
from typing import Any, Callable

from competitive_intel.agent import AGENT_PROMPT_VERSION, SYSTEM_INSTRUCTIONS
from competitive_intel.domain.agent import (
    AgentRunResult,
    AgentRunnerLimits,
    AgentState,
    ControlledRunContext,
    RunMode,
    TERMINAL_STATES,
    ToolResult,
    validate_transition,
)
from competitive_intel.infrastructure.agent import (
    AgentProvider,
    AgentProviderRequest,
)
from competitive_intel.persistence import Persistence

from .agent_tools import (
    TOOL_DEFINITIONS,
    AgentToolExecutor,
    validate_tool_arguments,
)


EventSink = Callable[[dict[str, Any]], None]

PERSISTED_STATE = {
    AgentState.INITIALIZING: "SOURCE_DISCOVERY",
    AgentState.PROFILE_LOOKUP: "SOURCE_DISCOVERY",
    AgentState.MODE_SELECTION: "SOURCE_DISCOVERY",
    AgentState.SOURCE_DISCOVERY: "SOURCE_DISCOVERY",
    AgentState.SOURCE_VALIDATION: "SOURCE_VALIDATION",
    AgentState.PAGE_FETCHING: "PAGE_FETCHING",
    AgentState.SNAPSHOT_PERSISTENCE: "PAGE_FETCHING",
    AgentState.FACT_EXTRACTION: "FACT_EXTRACTION",
    AgentState.FACT_PERSISTENCE: "FACT_EXTRACTION",
    AgentState.HISTORY_LOOKUP: "HISTORY_COMPARISON",
    AgentState.FACT_COMPARISON: "HISTORY_COMPARISON",
    AgentState.CHANGE_PERSISTENCE: "HISTORY_COMPARISON",
    AgentState.REPORT_GENERATION: "REPORT_GENERATION",
    AgentState.REPORT_PERSISTENCE: "REPORT_GENERATION",
    AgentState.RUN_SUMMARY: "REPORT_GENERATION",
    AgentState.COMPLETED: "COMPLETED",
    AgentState.COMPLETED_WITH_WARNINGS: "COMPLETED",
    AgentState.FAILED: "FAILED",
}


class AgentRunner:
    def __init__(
        self,
        persistence: Persistence,
        provider: AgentProvider,
        tools: AgentToolExecutor,
        *,
        limits: AgentRunnerLimits | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        self._persistence = persistence
        self._provider = provider
        self._tools = tools
        self._limits = limits or AgentRunnerLimits()
        self._emit = event_sink or (lambda event: None)

    def run(
        self,
        competitor_name: str,
        *,
        locale: str = "en-US",
        language: str | None = None,
    ) -> AgentRunResult:
        name = self._clean_input(competitor_name)
        normalized = name.casefold()
        with self._persistence.transaction() as session:
            run_id = self._persistence.agent_runs.create(
                session,
                input_name=competitor_name,
                normalized_input=normalized,
                run_mode="UNKNOWN",
                current_state=PERSISTED_STATE[AgentState.INITIALIZING],
                max_tool_calls=self._limits.max_tool_calls,
            )
        context = ControlledRunContext(
            run_id=run_id,
            competitor_name=name,
            normalized_name=normalized,
            current_state=AgentState.INITIALIZING,
            max_tool_calls=self._limits.max_tool_calls,
        )
        with self._persistence.transaction() as session:
            stage_id = self._create_stage(
                session, context, AgentState.INITIALIZING
            )
        self._emit_event("run_started", context)
        stage_id = self._transition(
            context, stage_id, AgentState.PROFILE_LOOKUP
        )

        messages: list[dict[str, Any]] = [
            {"role": "user", "content": f"Analyze competitor: {name}"}
        ]
        provider_calls: Counter[AgentState] = Counter()
        signatures: Counter[str] = Counter()

        while context.current_state not in TERMINAL_STATES:
            if context.remaining_tool_budget <= 0:
                return self._fail(
                    context,
                    stage_id,
                    "TOOL_BUDGET_EXHAUSTED",
                    "Global tool-call budget was exhausted.",
                )
            state = context.current_state
            provider_calls[state] += 1
            if (
                provider_calls[state]
                > self._limits.max_provider_calls_per_state
            ):
                return self._fail(
                    context,
                    stage_id,
                    "STATE_PROVIDER_BUDGET_EXHAUSTED",
                    f"Provider-call budget exhausted for {state.value}.",
                )
            allowed = self._tools.allowed_tools(state)
            request = AgentProviderRequest(
                system_instructions=SYSTEM_INSTRUCTIONS,
                conversation_messages=tuple(
                    messages[-self._limits.max_context_messages :]
                ),
                current_state=state,
                allowed_tools=allowed,
                tool_schemas=self._tools.schemas_for(allowed),
                remaining_tool_budget=context.remaining_tool_budget,
                run_context={
                    "run_id": context.run_id,
                    "competitor_name": context.competitor_name,
                    "normalized_name": context.normalized_name,
                    "run_mode": (
                        context.run_mode.value if context.run_mode else None
                    ),
                    "locale": locale,
                    "language": language,
                    "warnings_count": len(context.warnings),
                    "errors_count": len(context.errors),
                },
            )
            try:
                response = self._provider.choose_tools(request)
            except Exception as exc:
                return self._fail(
                    context,
                    stage_id,
                    "AGENT_PROVIDER_EXCEPTION",
                    f"{type(exc).__name__}: {exc}",
                )
            context.warnings.extend(response.warnings)
            if response.error:
                return self._fail(
                    context,
                    stage_id,
                    "AGENT_PROVIDER_ERROR",
                    response.error,
                )
            if len(response.tool_calls) != 1:
                return self._fail(
                    context,
                    stage_id,
                    "INVALID_TOOL_CALL_COUNT",
                    "AgentProvider must return exactly one tool call.",
                )
            call = response.tool_calls[0]
            if call.name not in TOOL_DEFINITIONS:
                return self._reject_requested_tool(
                    context,
                    stage_id,
                    call.name,
                    call.arguments,
                    "UNREGISTERED_TOOL",
                    f"AgentProvider requested unregistered tool {call.name!r}.",
                )
            if call.name not in allowed:
                return self._reject_requested_tool(
                    context,
                    stage_id,
                    call.name,
                    call.arguments,
                    "TOOL_NOT_ALLOWED",
                    f"Tool {call.name!r} is not allowed in {state.value}.",
                )
            valid, validation_error = validate_tool_arguments(
                TOOL_DEFINITIONS[call.name].parameters, call.arguments
            )
            if not valid:
                return self._reject_requested_tool(
                    context,
                    stage_id,
                    call.name,
                    call.arguments,
                    "INVALID_TOOL_ARGUMENTS",
                    validation_error or "Invalid tool arguments.",
                )
            signature = json.dumps(
                [call.name, call.arguments],
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            signatures[signature] += 1
            if signatures[signature] > self._limits.max_duplicate_attempts:
                return self._reject_requested_tool(
                    context,
                    stage_id,
                    call.name,
                    call.arguments,
                    "DUPLICATE_TOOL_CALL",
                    "Identical tool and arguments exceeded the retry limit.",
                )

            context.tool_call_count += 1
            self._emit_event(
                "tool_requested",
                context,
                tool=call.name,
                arguments=self._safe_value(call.arguments),
            )
            started = perf_counter()
            with self._persistence.transaction() as session:
                tool_call_id = self._persistence.tool_calls.create(
                    session,
                    run_id=context.run_id,
                    stage_event_id=stage_id,
                    call_index=context.tool_call_count,
                    tool_name=call.name,
                    input_summary=self._safe_value(call.arguments),
                )
            result = self._tools.execute(call.name, call.arguments, context)
            with self._persistence.transaction() as session:
                self._persistence.tool_calls.finish(
                    session,
                    tool_call_id,
                    status="SUCCEEDED" if result.ok else "FAILED",
                    output_summary=self._safe_value(result.data),
                    retryable=result.retryable,
                    duration_ms=max(0, int((perf_counter() - started) * 1000)),
                    error_code=result.error_code,
                    error_message=(result.error_message or "")[:500] or None,
                )
            context.tool_results[call.name] = result
            self._collect_messages(context, result)
            messages.extend(
                [
                    {
                        "role": "assistant",
                        "content": response.assistant_message[:500],
                    },
                    {
                        "role": "tool",
                        "name": call.name,
                        "content": self._safe_value(result.data),
                    },
                ]
            )
            self._emit_event(
                "tool_completed",
                context,
                tool=call.name,
                ok=result.ok,
                result=self._safe_value(result.data),
                error_code=result.error_code,
            )
            if not result.ok:
                if (
                    result.retryable
                    and signatures[signature]
                    < self._limits.max_duplicate_attempts
                ):
                    continue
                return self._fail(
                    context,
                    stage_id,
                    result.error_code or "TOOL_FAILED",
                    result.error_message or f"Tool {call.name} failed.",
                )
            stage_id = self._advance_after_tool(context, stage_id, call.name)

        return self._result(context)

    def _reject_requested_tool(
        self,
        context: ControlledRunContext,
        stage_id: int,
        tool_name: str,
        arguments: dict[str, Any],
        error_code: str,
        message: str,
    ) -> AgentRunResult:
        context.tool_call_count += 1
        with self._persistence.transaction() as session:
            call_id = self._persistence.tool_calls.create(
                session,
                run_id=context.run_id,
                stage_event_id=stage_id,
                call_index=context.tool_call_count,
                tool_name=tool_name[:100] or "invalid_tool",
                input_summary=self._safe_value(arguments),
            )
            self._persistence.tool_calls.finish(
                session,
                call_id,
                status="FAILED",
                output_summary={"rejected": True},
                retryable=False,
                duration_ms=0,
                error_code=error_code,
                error_message=message[:500],
            )
        return self._fail(
            context, stage_id, error_code, message
        )

    def _advance_after_tool(
        self,
        context: ControlledRunContext,
        stage_id: int,
        tool_name: str,
    ) -> int:
        if tool_name == "get_run_status":
            return stage_id
        if tool_name == "get_competitor_profile":
            data = context.tool_results[tool_name].data
            context.competitor_id = data.get("competitor_id")
            complete = bool(
                data.get("exists")
                and data.get("verified_source_count", 0) > 0
                and data.get("successful_snapshot_count", 0) > 0
                and data.get("confirmed_fact_count", 0) > 0
            )
            context.run_mode = (
                RunMode.REFRESH if complete else RunMode.BASELINE
            )
            stage_id = self._transition(
                context, stage_id, AgentState.MODE_SELECTION
            )
            with self._persistence.transaction() as session:
                self._persistence.agent_runs.update_context(
                    session,
                    context.run_id,
                    competitor_id=context.competitor_id,
                    run_mode=(
                        "TRACKING"
                        if context.run_mode == RunMode.REFRESH
                        else "BASELINE"
                    ),
                )
            self._emit_event(
                "mode_selected",
                context,
                run_mode=context.run_mode.value,
            )
            target = (
                AgentState.PAGE_FETCHING
                if complete else AgentState.SOURCE_DISCOVERY
            )
            return self._transition(context, stage_id, target)
        if tool_name == "discover_competitor_sources":
            data = context.tool_results[tool_name].data
            context.competitor_id = data.get("competitor_id")
            with self._persistence.transaction() as session:
                self._persistence.agent_runs.update_context(
                    session,
                    context.run_id,
                    competitor_id=context.competitor_id,
                )
            stage_id = self._transition(
                context, stage_id, AgentState.SOURCE_VALIDATION
            )
            return self._transition(
                context, stage_id, AgentState.PAGE_FETCHING
            )
        if tool_name == "refresh_verified_sources":
            stage_id = self._transition(
                context, stage_id, AgentState.SNAPSHOT_PERSISTENCE
            )
            return self._transition(
                context, stage_id, AgentState.FACT_EXTRACTION
            )
        if tool_name == "extract_competitor_facts":
            stage_id = self._transition(
                context, stage_id, AgentState.FACT_PERSISTENCE
            )
            if context.run_mode == RunMode.BASELINE:
                self._tools.establish_baseline(context)
                return self._transition(
                    context, stage_id, AgentState.REPORT_GENERATION
                )
            return self._transition(
                context, stage_id, AgentState.HISTORY_LOOKUP
            )
        if tool_name == "get_previous_fact_baseline":
            return self._transition(
                context, stage_id, AgentState.FACT_COMPARISON
            )
        if tool_name == "compare_competitor_facts":
            stage_id = self._transition(
                context, stage_id, AgentState.CHANGE_PERSISTENCE
            )
            return self._transition(
                context, stage_id, AgentState.REPORT_GENERATION
            )
        if tool_name == "generate_competitor_report":
            stage_id = self._transition(
                context, stage_id, AgentState.REPORT_PERSISTENCE
            )
            return self._transition(
                context, stage_id, AgentState.RUN_SUMMARY
            )
        if tool_name == "finalize_run_summary":
            target = (
                AgentState.COMPLETED_WITH_WARNINGS
                if context.warnings or context.errors else AgentState.COMPLETED
            )
            if context.summary is not None:
                object.__setattr__(context.summary, "final_state", target)
            stage_id = self._transition(context, stage_id, target)
            status = "COMPLETED"
            with self._persistence.transaction() as session:
                self._persistence.stage_events.finish(
                    session, stage_id, status="SUCCEEDED"
                )
                self._persistence.agent_runs.finish(
                    session,
                    context.run_id,
                    status=status,
                    current_state=PERSISTED_STATE[target],
                )
            self._emit_event("run_completed", context)
            return stage_id
        raise RuntimeError(f"No deterministic transition for tool {tool_name}")

    def _transition(
        self,
        context: ControlledRunContext,
        current_stage_id: int,
        target: AgentState,
    ) -> int:
        validate_transition(context.current_state, target)
        previous = context.current_state
        with self._persistence.transaction() as session:
            self._persistence.stage_events.finish(
                session, current_stage_id, status="SUCCEEDED"
            )
            new_stage_id = self._create_stage(session, context, target)
            self._persistence.agent_runs.update_context(
                session,
                context.run_id,
                current_state=PERSISTED_STATE[target],
            )
        context.completed_states.append(previous)
        context.current_state = target
        context.transitions.append((previous, target))
        self._emit_event(
            "state_transition",
            context,
            previous=previous.value,
            target=target.value,
        )
        return new_stage_id

    def _fail(
        self,
        context: ControlledRunContext,
        stage_id: int,
        error_code: str,
        message: str,
    ) -> AgentRunResult:
        context.errors.append(message[:500])
        previous = context.current_state
        if previous != AgentState.FAILED:
            validate_transition(previous, AgentState.FAILED)
            with self._persistence.transaction() as session:
                self._persistence.stage_events.finish(
                    session,
                    stage_id,
                    status="FAILED",
                    error_code=error_code,
                    error_message=message[:500],
                )
                failed_stage = self._persistence.stage_events.create(
                    session,
                    run_id=context.run_id,
                    stage=AgentState.FAILED.value,
                    attempt_no=1,
                    max_attempts=1,
                    details={"error_code": error_code},
                )
                self._persistence.stage_events.finish(
                    session,
                    failed_stage,
                    status="FAILED",
                    error_code=error_code,
                    error_message=message[:500],
                )
                self._persistence.agent_runs.finish(
                    session,
                    context.run_id,
                    status="FAILED",
                    current_state=PERSISTED_STATE[AgentState.FAILED],
                    error_code=error_code,
                    error_message=message[:500],
                )
            context.current_state = AgentState.FAILED
            context.transitions.append((previous, AgentState.FAILED))
        self._emit_event(
            "run_failed", context, error_code=error_code, message=message[:500]
        )
        return self._result(context)

    def _create_stage(
        self, session, context: ControlledRunContext, state: AgentState
    ) -> int:
        persisted = PERSISTED_STATE[state]
        attempt = context.persisted_stage_attempts.get(persisted, 0) + 1
        context.persisted_stage_attempts[persisted] = attempt
        return self._persistence.stage_events.create(
            session,
            run_id=context.run_id,
            stage=persisted,
            attempt_no=attempt,
            max_attempts=10,
            details={
                "logical_state": state.value,
                "allowed_tools": list(self._tools.allowed_tools(state)),
                "provider": self._provider.name,
                "model": self._provider.model,
                "prompt_version": AGENT_PROMPT_VERSION,
            },
        )

    def _collect_messages(
        self, context: ControlledRunContext, result: ToolResult
    ) -> None:
        warnings = result.data.get("warnings", [])
        errors = result.data.get("errors", [])
        context.warnings.extend(str(item)[:500] for item in warnings[:20])
        context.errors.extend(str(item)[:500] for item in errors[:20])

    def _result(self, context: ControlledRunContext) -> AgentRunResult:
        return AgentRunResult(
            run_id=context.run_id,
            run_mode=context.run_mode,
            final_state=context.current_state,
            summary=context.summary,
            tool_call_count=context.tool_call_count,
            transitions=tuple(context.transitions),
            warnings=tuple(context.warnings),
            errors=tuple(context.errors),
        )

    def _emit_event(
        self, event_type: str, context: ControlledRunContext, **details: Any
    ) -> None:
        self._emit(
            {
                "event": event_type,
                "run_id": context.run_id,
                "state": context.current_state.value,
                **details,
            }
        )

    @staticmethod
    def _safe_value(value: Any) -> Any:
        secret_fragments = ("password", "secret", "api_key", "token")
        if isinstance(value, dict):
            return {
                str(key): (
                    "[REDACTED]"
                    if any(fragment in str(key).casefold() for fragment in secret_fragments)
                    else AgentRunner._safe_value(item)
                )
                for key, item in list(value.items())[:50]
            }
        if isinstance(value, (list, tuple)):
            return [AgentRunner._safe_value(item) for item in list(value)[:50]]
        if isinstance(value, str):
            return value[:1000]
        return value

    @staticmethod
    def _clean_input(value: str) -> str:
        cleaned = value.strip()
        if cleaned.casefold().startswith("分析"):
            cleaned = cleaned[2:].strip()
        if not cleaned or len(cleaned) > 255:
            raise ValueError("Competitor name must contain 1 to 255 characters.")
        return cleaned

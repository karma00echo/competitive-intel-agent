"""Deterministic offline AgentProvider for controlled-runner tests."""

from __future__ import annotations

from competitive_intel.domain.agent import AgentState

from .base import (
    AgentProviderRequest,
    AgentProviderResponse,
    AgentToolCall,
)


DEFAULT_TOOL_BY_STATE = {
    AgentState.PROFILE_LOOKUP: "get_competitor_profile",
    AgentState.SOURCE_DISCOVERY: "discover_competitor_sources",
    AgentState.PAGE_FETCHING: "refresh_verified_sources",
    AgentState.FACT_EXTRACTION: "extract_competitor_facts",
    AgentState.RUN_SUMMARY: "finalize_run_summary",
}


class FixtureAgentProvider:
    def __init__(
        self,
        overrides: dict[AgentState, AgentToolCall | None] | None = None,
    ) -> None:
        self._overrides = overrides or {}
        self.requests: list[AgentProviderRequest] = []

    @property
    def name(self) -> str:
        return "fixture"

    @property
    def model(self) -> str:
        return "fixture-tool-caller-v1"

    def choose_tools(
        self, request: AgentProviderRequest
    ) -> AgentProviderResponse:
        self.requests.append(request)
        index = len(self.requests)
        if request.current_state in self._overrides:
            call = self._overrides[request.current_state]
        else:
            tool_name = DEFAULT_TOOL_BY_STATE.get(request.current_state)
            call = (
                self._default_call(tool_name, request, index)
                if tool_name is not None
                else None
            )
        calls = (call,) if call is not None else ()
        return AgentProviderResponse(
            assistant_message=(
                f"Requesting {call.name} for {request.current_state.value}."
                if call else "No tool selected."
            ),
            tool_calls=calls,
            provider=self.name,
            model=self.model,
            request_id=f"fixture-agent-{index}",
            usage={"input_messages": len(request.conversation_messages), "output_calls": len(calls)},
        )

    def _default_call(
        self,
        tool_name: str,
        request: AgentProviderRequest,
        index: int,
    ) -> AgentToolCall:
        competitor = str(request.run_context["competitor_name"])
        if tool_name == "discover_competitor_sources":
            arguments = {
                "competitor_name": competitor,
                "locale": request.run_context.get("locale", "en-US"),
                "language": request.run_context.get("language"),
            }
        elif tool_name in {
            "get_competitor_profile",
            "refresh_verified_sources",
            "extract_competitor_facts",
        }:
            arguments = {"competitor_name": competitor}
        else:
            arguments = {}
        return AgentToolCall(
            f"fixture-call-{index}", tool_name, arguments
        )

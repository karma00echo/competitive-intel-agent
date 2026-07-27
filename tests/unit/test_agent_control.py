from __future__ import annotations

import pytest

from competitive_intel.agent import AGENT_PROMPT_VERSION, SYSTEM_INSTRUCTIONS
from competitive_intel.domain.agent import (
    AgentState,
    InvalidStateTransition,
    validate_transition,
)
from competitive_intel.infrastructure.agent import (
    AgentProviderRequest,
    FixtureAgentProvider,
)
from competitive_intel.services.agent_runner import AgentRunner
from competitive_intel.services.agent_tools import (
    TOOL_DEFINITIONS,
    AgentToolExecutor,
    validate_tool_arguments,
)


def _request(state: AgentState) -> AgentProviderRequest:
    tools = AgentToolExecutor(None, None, None, None)  # type: ignore[arg-type]
    allowed = tools.allowed_tools(state)
    return AgentProviderRequest(
        SYSTEM_INSTRUCTIONS,
        (),
        state,
        allowed,
        tools.schemas_for(allowed),
        10,
        {
            "run_id": 1,
            "competitor_name": "Notion",
            "locale": "en-US",
            "language": None,
        },
    )


def test_versioned_prompt_contains_required_safety_rules() -> None:
    assert AGENT_PROMPT_VERSION == "controlled-agent-v2"
    for phrase in (
        "not a general chat assistant",
        "Never invent tool results",
        "failed fetch",
        "Contact Sales",
        "Never invent a URL",
        "tool budget",
    ):
        assert phrase in SYSTEM_INSTRUCTIONS


def test_legal_and_illegal_state_transitions() -> None:
    validate_transition(AgentState.INITIALIZING, AgentState.PROFILE_LOOKUP)
    validate_transition(AgentState.MODE_SELECTION, AgentState.SOURCE_DISCOVERY)
    validate_transition(AgentState.MODE_SELECTION, AgentState.PAGE_FETCHING)
    with pytest.raises(InvalidStateTransition):
        validate_transition(
            AgentState.PROFILE_LOOKUP, AgentState.FACT_EXTRACTION
        )


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        (AgentState.PROFILE_LOOKUP, "get_competitor_profile"),
        (AgentState.SOURCE_DISCOVERY, "discover_competitor_sources"),
        (AgentState.PAGE_FETCHING, "refresh_verified_sources"),
        (AgentState.FACT_EXTRACTION, "extract_competitor_facts"),
        (AgentState.HISTORY_LOOKUP, "get_previous_fact_baseline"),
        (AgentState.FACT_COMPARISON, "compare_competitor_facts"),
        (AgentState.REPORT_GENERATION, "generate_competitor_report"),
        (AgentState.RUN_SUMMARY, "finalize_run_summary"),
    ],
)
def test_fixture_agent_provider_selects_deterministic_allowed_tool(
    state, expected
) -> None:
    provider = FixtureAgentProvider()
    response = provider.choose_tools(_request(state))
    assert response.provider == "fixture"
    assert response.model == "fixture-tool-caller-v1"
    assert response.tool_calls[0].name == expected
    assert expected in _request(state).allowed_tools


def test_tool_whitelists_are_state_specific() -> None:
    tools = AgentToolExecutor(None, None, None, None)  # type: ignore[arg-type]
    assert "discover_competitor_sources" in tools.allowed_tools(
        AgentState.SOURCE_DISCOVERY
    )
    assert "discover_competitor_sources" not in tools.allowed_tools(
        AgentState.PAGE_FETCHING
    )
    assert "get_run_status" in tools.allowed_tools(AgentState.FACT_EXTRACTION)
    assert "compare_competitor_facts" in tools.allowed_tools(
        AgentState.FACT_COMPARISON
    )
    assert "compare_competitor_facts" not in tools.allowed_tools(
        AgentState.REPORT_GENERATION
    )


def test_strict_tool_argument_schema_rejects_missing_unknown_and_wrong_type() -> None:
    schema = TOOL_DEFINITIONS["get_competitor_profile"].parameters
    assert validate_tool_arguments(
        schema, {"competitor_name": "Notion"}
    ) == (True, None)
    assert not validate_tool_arguments(schema, {})[0]
    assert not validate_tool_arguments(
        schema, {"competitor_name": "Notion", "url": "https://example.com"}
    )[0]
    assert not validate_tool_arguments(schema, {"competitor_name": 3})[0]


def test_sensitive_values_are_redacted_and_long_strings_are_bounded() -> None:
    value = AgentRunner._safe_value(
        {"api_key": "secret-value", "content": "x" * 5000}
    )
    assert value["api_key"] == "[REDACTED]"
    assert len(value["content"]) == 1000

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from competitive_intel.agent import AGENT_PROMPT_VERSION
from competitive_intel.cli import exit_code_for_state, main
from competitive_intel.domain.agent import (
    AgentRunnerLimits,
    AgentState,
    RunMode,
    ToolResult,
)
from competitive_intel.domain.urls import normalize_url
from competitive_intel.domain.webpage import FetchStatus
from competitive_intel.infrastructure.agent import (
    AgentToolCall,
    FixtureAgentProvider,
)
from competitive_intel.infrastructure.facts import FixtureFactExtractionProvider
from competitive_intel.infrastructure.http.fixture_fetcher import FixturePageFetcher
from competitive_intel.infrastructure.search.providers.fixture import (
    FixtureSearchProvider,
)
from competitive_intel.services.agent_runner import AgentRunner
from competitive_intel.services.agent_tools import AgentToolExecutor
from competitive_intel.services.fact_extraction_service import (
    FactExtractionService,
)
from competitive_intel.services.snapshot_service import SnapshotService
from competitive_intel.services.source_discovery_service import (
    SourceDiscoveryService,
)


def _build_runner(
    persistence,
    *,
    provider=None,
    limits=None,
    fetcher=None,
    events=None,
):
    fetcher = fetcher or FixturePageFetcher()
    source = SourceDiscoveryService(
        persistence, FixtureSearchProvider(), fetcher
    )
    snapshots = SnapshotService(persistence, fetcher)
    facts = FactExtractionService(
        persistence, FixtureFactExtractionProvider()
    )
    tools = AgentToolExecutor(persistence, source, snapshots, facts)
    provider = provider or FixtureAgentProvider()
    runner = AgentRunner(
        persistence,
        provider,
        tools,
        limits=limits,
        event_sink=(events.append if events is not None else None),
    )
    return runner, provider


def test_notion_complete_offline_baseline_and_audit(persistence) -> None:
    events = []
    runner, provider = _build_runner(persistence, events=events)
    result = runner.run("Notion")

    assert result.run_mode == RunMode.BASELINE
    assert result.final_state == AgentState.COMPLETED
    assert result.tool_call_count == 6
    assert result.summary is not None
    assert result.summary.verified_source_count == 4
    assert result.summary.baseline_page_count == 4
    assert result.summary.confirmed_fact_count == 9
    assert result.summary.official_homepage == "https://www.notion.so/"
    assert any(event["event"] == "mode_selected" for event in events)
    assert all(
        "clean_content" not in json.dumps(request.run_context)
        for request in provider.requests
    )

    with persistence.transaction() as session:
        run = persistence.agent_runs.get(session, result.run_id)
        stages = persistence.stage_events.list_for_run(session, result.run_id)
        calls = persistence.tool_calls.list_for_run(session, result.run_id)
    assert run["run_mode"] == "BASELINE"
    assert run["status"] == "COMPLETED"
    assert run["tool_call_count"] == 6
    assert len(calls) == 6
    assert all(call["status"] == "SUCCEEDED" for call in calls)
    details = " ".join(str(stage["details_json"]) for stage in stages)
    assert AGENT_PROMPT_VERSION in details
    assert "fixture-tool-caller-v1" in details
    assert {
        "SOURCE_DISCOVERY",
        "SOURCE_VALIDATION",
        "PAGE_FETCHING",
        "FACT_EXTRACTION",
        "REPORT_GENERATION",
        "COMPLETED",
    } <= {stage["stage"] for stage in stages}


def test_feishu_complete_offline_baseline(persistence) -> None:
    runner, _ = _build_runner(persistence)
    result = runner.run("飞书", language="zh")
    assert result.run_mode == RunMode.BASELINE
    assert result.final_state == AgentState.COMPLETED
    assert result.summary is not None
    assert result.summary.verified_source_count == 2
    assert result.summary.confirmed_fact_count == 2


def test_second_run_is_refresh_and_uses_current_snapshots(persistence) -> None:
    first, _ = _build_runner(persistence)
    assert first.run("Notion").final_state == AgentState.COMPLETED

    second, _ = _build_runner(persistence)
    result = second.run("Notion")
    assert result.run_mode == RunMode.REFRESH
    assert result.final_state == AgentState.COMPLETED
    assert result.summary is not None
    assert result.summary.unchanged_page_count == 4
    assert result.summary.baseline_page_count == 0
    assert result.summary.confirmed_fact_count == 9
    with persistence.transaction() as session:
        run = persistence.agent_runs.get(session, result.run_id)
        facts = persistence.product_facts.list_for_run(session, result.run_id)
    assert run["run_mode"] == "TRACKING"
    assert len(facts) == 9


def test_existing_competitor_without_verified_sources_reenters_discovery(
    persistence,
) -> None:
    with persistence.transaction() as session:
        persistence.competitors.create(
            session,
            canonical_name="Notion",
            normalized_name="notion",
        )
    runner, _ = _build_runner(persistence)
    result = runner.run("Notion")
    assert result.run_mode == RunMode.BASELINE
    assert (
        AgentState.MODE_SELECTION,
        AgentState.SOURCE_DISCOVERY,
    ) in result.transitions
    assert result.final_state == AgentState.COMPLETED


@pytest.mark.parametrize(
    ("override", "error_fragment"),
    [
        (
            AgentToolCall("bad", "not_registered", {}),
            "unregistered",
        ),
        (
            AgentToolCall(
                "bad",
                "refresh_verified_sources",
                {"competitor_name": "Notion"},
            ),
            "not allowed",
        ),
        (
            AgentToolCall("bad", "get_competitor_profile", {}),
            "Missing arguments",
        ),
    ],
)
def test_invalid_tool_requests_fail_deterministically(
    persistence, override, error_fragment
) -> None:
    provider = FixtureAgentProvider(
        {AgentState.PROFILE_LOOKUP: override}
    )
    runner, _ = _build_runner(persistence, provider=provider)
    result = runner.run("Notion")
    assert result.final_state == AgentState.FAILED
    assert any(error_fragment in error for error in result.errors)
    with persistence.transaction() as session:
        calls = persistence.tool_calls.list_for_run(session, result.run_id)
    assert len(calls) == 1
    assert calls[0]["status"] == "FAILED"


def test_empty_tool_calls_fail_deterministically(persistence) -> None:
    provider = FixtureAgentProvider(
        {AgentState.PROFILE_LOOKUP: None}
    )
    runner, _ = _build_runner(persistence, provider=provider)
    result = runner.run("Notion")
    assert result.final_state == AgentState.FAILED
    assert "exactly one tool call" in result.errors[-1]


def test_repeated_status_tool_is_bounded(persistence) -> None:
    provider = FixtureAgentProvider(
        {
            AgentState.PROFILE_LOOKUP: AgentToolCall(
                "status", "get_run_status", {}
            )
        }
    )
    runner, _ = _build_runner(
        persistence,
        provider=provider,
        limits=AgentRunnerLimits(
            max_tool_calls=10,
            max_provider_calls_per_state=3,
            max_duplicate_attempts=1,
        ),
    )
    result = runner.run("Notion")
    assert result.final_state == AgentState.FAILED
    assert "retry limit" in result.errors[-1]


def test_global_tool_budget_stops_before_unbounded_loop(persistence) -> None:
    runner, _ = _build_runner(
        persistence,
        limits=AgentRunnerLimits(max_tool_calls=4),
    )
    result = runner.run("Notion")
    assert result.final_state == AgentState.FAILED
    assert result.tool_call_count == 4
    assert "budget" in result.errors[-1].casefold()


def test_per_state_provider_call_budget_is_enforced(persistence) -> None:
    provider = FixtureAgentProvider(
        {
            AgentState.PROFILE_LOOKUP: AgentToolCall(
                "status", "get_run_status", {}
            )
        }
    )
    runner, _ = _build_runner(
        persistence,
        provider=provider,
        limits=AgentRunnerLimits(
            max_tool_calls=10,
            max_provider_calls_per_state=2,
            max_duplicate_attempts=10,
        ),
    )
    result = runner.run("Notion")
    assert result.final_state == AgentState.FAILED
    assert "Provider-call budget" in result.errors[-1]


class FailingToolWrapper:
    def __init__(self, base, *, retryable: bool):
        self.base = base
        self.retryable = retryable
        self.profile_calls = 0

    def allowed_tools(self, state):
        return self.base.allowed_tools(state)

    def schemas_for(self, names):
        return self.base.schemas_for(names)

    def execute(self, name, arguments, context):
        if name == "get_competitor_profile":
            self.profile_calls += 1
            if self.profile_calls == 1:
                return ToolResult(
                    False,
                    error_code="FIXTURE_TOOL_FAILURE",
                    error_message="fixture tool failure",
                    retryable=self.retryable,
                )
        return self.base.execute(name, arguments, context)

    def establish_baseline(self, context):
        return self.base.establish_baseline(context)


def test_retryable_tool_error_retries_once_and_completes(persistence) -> None:
    base_runner, provider = _build_runner(persistence)
    wrapped = FailingToolWrapper(base_runner._tools, retryable=True)
    runner = AgentRunner(
        persistence,
        provider,
        wrapped,
        limits=AgentRunnerLimits(max_duplicate_attempts=2),
    )
    result = runner.run("Notion")
    assert result.final_state == AgentState.COMPLETED
    assert result.tool_call_count == 7
    assert wrapped.profile_calls == 2


def test_non_retryable_tool_error_fails_immediately(persistence) -> None:
    base_runner, provider = _build_runner(persistence)
    wrapped = FailingToolWrapper(base_runner._tools, retryable=False)
    runner = AgentRunner(persistence, provider, wrapped)
    result = runner.run("Notion")
    assert result.final_state == AgentState.FAILED
    assert result.tool_call_count == 1
    assert wrapped.profile_calls == 1


class OnePageFailingFetcher(FixturePageFetcher):
    def __init__(self):
        super().__init__()
        self.counts = {}

    def fetch(self, request):
        normalized = normalize_url(request.url)
        self.counts[normalized] = self.counts.get(normalized, 0) + 1
        result = super().fetch(request)
        if (
            normalized == "https://www.notion.so/pricing"
            and self.counts[normalized] >= 2
        ):
            return replace(
                result,
                raw_html=None,
                fetch_status=FetchStatus.FAILED,
                error_code="FIXTURE_CONNECTION_FAILURE",
                error_message="Fixture connection failed.",
            )
        return result


def test_single_page_failure_completes_with_warnings(persistence) -> None:
    runner, _ = _build_runner(
        persistence, fetcher=OnePageFailingFetcher()
    )
    result = runner.run("Notion")
    assert result.final_state == AgentState.COMPLETED_WITH_WARNINGS
    assert result.summary is not None
    assert result.summary.page_fetch_success_count == 3
    assert result.summary.page_fetch_failure_count == 1
    assert result.summary.confirmed_fact_count == 4
    assert exit_code_for_state(result.final_state) == 2


def test_critical_official_source_failure_is_failed(persistence) -> None:
    runner, _ = _build_runner(persistence)
    result = runner.run("Unknown Product")
    assert result.final_state == AgentState.FAILED
    assert "VERIFIED official source" in result.errors[-1]


class FactProviderMustNotRun:
    name = "fixture"

    def extract(self, request):
        raise AssertionError("fixture facts must not run for real content")


def test_real_content_mode_skips_fixture_fact_extraction(persistence) -> None:
    fetcher = FixturePageFetcher()
    source = SourceDiscoveryService(
        persistence, FixtureSearchProvider(), fetcher
    )
    snapshots = SnapshotService(persistence, fetcher)
    facts = FactExtractionService(persistence, FactProviderMustNotRun())
    tools = AgentToolExecutor(
        persistence,
        source,
        snapshots,
        facts,
        skip_fact_extraction=True,
        search_provider="serper",
        fetch_mode="real",
        agent_provider="fixture",
        fact_provider="fixture",
    )
    result = AgentRunner(
        persistence, FixtureAgentProvider(), tools
    ).run("Notion")
    assert result.final_state == AgentState.COMPLETED_WITH_WARNINGS
    assert result.summary is not None
    assert result.summary.confirmed_fact_count == 0
    assert result.summary.fact_extraction_status == "SKIPPED"
    assert result.summary.fact_extraction_reason == (
        "REAL_CONTENT_REQUIRES_REAL_FACT_PROVIDER"
    )
    assert result.summary.search_provider == "serper"
    assert result.summary.fetch_mode == "real"
    with persistence.transaction() as session:
        facts_for_run = persistence.product_facts.list_for_run(
            session, result.run_id
        )
        calls = persistence.tool_calls.list_for_run(session, result.run_id)
    assert facts_for_run == []
    assert "skip_fact_extraction" in {
        item["tool_name"] for item in calls
    }
    assert "extract_competitor_facts" not in {
        item["tool_name"] for item in calls
    }


def test_cli_exit_code_contract_and_configuration_error(capsys) -> None:
    assert exit_code_for_state(AgentState.COMPLETED) == 0
    assert exit_code_for_state(AgentState.COMPLETED_WITH_WARNINGS) == 2
    assert exit_code_for_state(AgentState.FAILED) == 1
    assert main(["analyze", "", "--agent-provider", "unknown"]) == 64
    assert "Configuration error" in capsys.readouterr().err

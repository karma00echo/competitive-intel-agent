from __future__ import annotations

import json

from competitive_intel.cli import main
from competitive_intel.domain.agent import AgentState, RunMode
from competitive_intel.infrastructure.agent import FixtureAgentProvider
from competitive_intel.infrastructure.facts import FixtureFactExtractionProvider
from competitive_intel.infrastructure.http.fixture_fetcher import FixturePageFetcher
from competitive_intel.infrastructure.search.providers.fixture import (
    FixtureSearchProvider,
)
from competitive_intel.services.agent_runner import AgentRunner
from competitive_intel.services.agent_tools import AgentToolExecutor
from competitive_intel.services.fact_extraction_service import FactExtractionService
from competitive_intel.services.fact_history_service import FactHistoryService
from competitive_intel.services.snapshot_service import SnapshotService
from competitive_intel.services.source_discovery_service import SourceDiscoveryService


def _runner(persistence, scenario: str = "unchanged") -> AgentRunner:
    fetcher = FixturePageFetcher(scenario=scenario)
    source = SourceDiscoveryService(
        persistence, FixtureSearchProvider(), fetcher
    )
    snapshots = SnapshotService(persistence, fetcher)
    facts = FactExtractionService(
        persistence, FixtureFactExtractionProvider(scenario=scenario)
    )
    return AgentRunner(
        persistence,
        FixtureAgentProvider(),
        AgentToolExecutor(persistence, source, snapshots, facts),
    )

def _competitor_id(persistence) -> int:
    with persistence.transaction() as session:
        competitor = persistence.competitors.get_by_normalized_name(
            session, "notion"
        )
    assert competitor is not None
    return int(competitor["id"])


def test_baseline_and_unchanged_refresh_reuse_fact_versions(persistence) -> None:
    baseline = _runner(persistence).run("Notion")
    assert baseline.final_state == AgentState.COMPLETED
    assert baseline.summary.report_type == "BASELINE_REPORT"
    assert baseline.summary.report_id is not None

    refresh = _runner(persistence).run("Notion")
    assert refresh.run_mode == RunMode.REFRESH
    assert refresh.summary.report_type == "CHANGE_TRACKING_REPORT"
    assert refresh.summary.added_count == 0
    assert refresh.summary.removed_count == 0
    assert refresh.summary.modified_count == 0
    assert refresh.summary.unchanged_count == 9
    assert refresh.summary.uncomparable_count == 0
    assert refresh.summary.duplicate_fact_count == 0
    assert refresh.summary.historical_reuse_count == 9

    competitor_id = _competitor_id(persistence)
    with persistence.transaction() as session:
        current = persistence.fact_versions.list_current(session, competitor_id)
        first_facts = persistence.fact_observations.list_for_run(
            session, baseline.run_id
        )
        second_facts = persistence.fact_observations.list_for_run(
            session, refresh.run_id
        )
        changes = persistence.changes.list_for_run(session, refresh.run_id)
    assert len(current) == len(first_facts) == len(second_facts) == 9
    assert {item["id"] for item in first_facts} == {
        item["id"] for item in second_facts
    }
    assert len(changes) == 9


def test_price_modified_refresh_creates_one_new_version(persistence) -> None:
    _runner(persistence).run("Notion")
    refresh = _runner(persistence, "price_changed").run("Notion")
    assert refresh.summary.modified_count == 1
    assert refresh.summary.unchanged_count == 8
    competitor_id = _competitor_id(persistence)
    with persistence.transaction() as session:
        changes = persistence.changes.list_for_run(session, refresh.run_id)
        history = persistence.fact_versions.list_history(
            session,
            competitor_id,
            "price.plus.month.user.annual_billing",
        )
    modified = [item for item in changes if item["change_type"] == "MODIFIED"]
    assert len(modified) == 1
    assert modified[0]["old_fact_id"] != modified[0]["new_fact_id"]
    assert len(history) == 2
    assert sum(bool(item["is_current"]) for item in history) == 1
    with persistence.transaction() as session:
        report = persistence.reports.get_for_run(
            session, refresh.run_id, "CHANGE_TRACKING"
        )
    assert "INFERENCE" in report["content_markdown"]
    assert "price.plus.month.user.annual_billing" in report["content_markdown"]


def test_feature_added_and_removed_refresh(persistence) -> None:
    _runner(persistence).run("Notion")
    added = _runner(persistence, "feature_added").run("Notion")
    assert added.summary.added_count == 1
    assert added.summary.unchanged_count == 9

    # The added run is now the valid baseline, so returning to the default
    # fixture reliably removes Enterprise Search.
    removed = _runner(persistence, "unchanged").run("Notion")
    assert removed.summary.removed_count == 1
    assert removed.summary.unchanged_count == 9


def test_feature_removed_fixture_requires_successful_source(persistence) -> None:
    _runner(persistence).run("Notion")
    removed = _runner(persistence, "feature_removed").run("Notion")
    assert removed.summary.removed_count == 1
    assert removed.summary.unchanged_count == 8
    assert removed.summary.uncomparable_count == 0


def test_failed_page_is_uncomparable_not_removed(persistence) -> None:
    _runner(persistence).run("Notion")
    refresh = _runner(persistence, "page_failure").run("Notion")
    assert refresh.final_state == AgentState.COMPLETED_WITH_WARNINGS
    assert refresh.summary.removed_count == 0
    assert refresh.summary.uncomparable_count == 5
    assert refresh.summary.unchanged_count == 4
    competitor_id = _competitor_id(persistence)
    with persistence.transaction() as session:
        current = persistence.fact_versions.list_current(session, competitor_id)
    assert len(current) == 9


def test_completed_with_warnings_is_an_explicit_valid_baseline(persistence) -> None:
    _runner(persistence).run("Notion")
    warning_run = _runner(persistence, "page_failure").run("Notion")
    assert warning_run.final_state == AgentState.COMPLETED_WITH_WARNINGS
    competitor_id = _competitor_id(persistence)
    with persistence.transaction() as session:
        failed_run = persistence.agent_runs.create(
            session,
            competitor_id=competitor_id,
            input_name="Notion",
            normalized_input="notion",
            run_mode="TRACKING",
            current_state="FAILED",
        )
        persistence.agent_runs.finish(
            session,
            failed_run,
            status="FAILED",
            current_state="FAILED",
            error_code="FIXTURE_FAILURE",
        )
    current = _runner(persistence).run("Notion")
    baseline = FactHistoryService(persistence).get_previous_baseline(
        competitor_id, current.run_id
    )
    assert baseline.previous_successful_run_id == warning_run.run_id


def test_feishu_unchanged_refresh_report(persistence) -> None:
    baseline = _runner(persistence).run("分析飞书", language="zh")
    refresh = _runner(persistence).run("飞书", language="zh")
    assert baseline.summary.report_type == "BASELINE_REPORT"
    assert refresh.summary.report_type == "CHANGE_TRACKING_REPORT"
    assert refresh.summary.unchanged_count == 2


def test_change_writes_are_idempotent_and_history_queries_work(persistence) -> None:
    baseline = _runner(persistence).run("Notion")
    refresh = _runner(persistence, "price_changed").run("Notion")
    history = FactHistoryService(persistence)
    competitor_id = _competitor_id(persistence)
    first = history.compare_and_persist(
        competitor_id, refresh.run_id, baseline.run_id
    )
    second = history.compare_and_persist(
        competitor_id, refresh.run_id, baseline.run_id
    )
    assert first.change_ids == second.change_ids
    with persistence.transaction() as session:
        changes = persistence.changes.list_for_run(session, refresh.run_id)
        fact_changes = persistence.changes.list_for_fact_key(
            session, competitor_id, "price.plus.month.user.annual_billing"
        )
        current = persistence.fact_versions.list_current(
            session, competitor_id
        )
    assert len(changes) == 9
    assert fact_changes
    assert len(current) == 9


def test_report_json_markdown_audit_and_cli_show_export(
    persistence, monkeypatch, tmp_path, capsys
) -> None:
    baseline = _runner(persistence).run("Notion")
    refresh = _runner(persistence).run("Notion")
    with persistence.transaction() as session:
        report = persistence.reports.get_for_run(
            session, refresh.run_id, "CHANGE_TRACKING"
        )
        stages = persistence.stage_events.list_for_run(session, refresh.run_id)
        calls = persistence.tool_calls.list_for_run(session, refresh.run_id)
    assert report["content_markdown"].startswith("# Notion")
    summary = json.loads(report["summary_json"])
    assert summary["content_json"]["report_type"] == "CHANGE_TRACKING_REPORT"
    logical_states = {
        json.loads(item["details_json"])["logical_state"] for item in stages
    }
    assert {
        "HISTORY_LOOKUP",
        "FACT_COMPARISON",
        "CHANGE_PERSISTENCE",
        "REPORT_GENERATION",
        "REPORT_PERSISTENCE",
    } <= logical_states
    assert {
        "get_previous_fact_baseline",
        "compare_competitor_facts",
        "generate_competitor_report",
    } <= {item["tool_name"] for item in calls}

    url = persistence.database.engine.url
    monkeypatch.setenv("DB_HOST", url.host)
    monkeypatch.setenv("DB_PORT", str(url.port))
    monkeypatch.setenv("DB_NAME", url.database)
    monkeypatch.setenv("DB_USER", url.username)
    monkeypatch.setenv("DB_PASSWORD", url.password or "")
    assert main(["report", "show", "--run-id", str(baseline.run_id)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["report_type"] == "BASELINE_REPORT"
    assert main([
        "report", "show", "--competitor", "Notion", "--latest"
    ]) == 0
    latest = json.loads(capsys.readouterr().out)
    assert latest["report_type"] == "CHANGE_TRACKING_REPORT"

    output = tmp_path / "notion.md"
    assert main([
        "report", "export", "--run-id", str(refresh.run_id),
        "--format", "markdown", "--output", str(output),
    ]) == 0
    assert output.read_text(encoding="utf-8").startswith("# Notion")
    json_output = tmp_path / "notion.json"
    assert main([
        "report", "export", "--run-id", str(refresh.run_id),
        "--format", "json", "--output", str(json_output),
    ]) == 0
    exported = json.loads(json_output.read_text(encoding="utf-8"))
    assert exported["report_type"] == "CHANGE_TRACKING_REPORT"
    by_id = tmp_path / "by-id.md"
    assert main([
        "report", "export", "--report-id", str(report["id"]),
        "--format", "markdown", "--output", str(by_id),
    ]) == 0
    assert by_id.read_text(encoding="utf-8").startswith("# Notion")
    latest_output = tmp_path / "latest.json"
    assert main([
        "report", "export", "--competitor", "Notion", "--latest",
        "--format", "json", "--output", str(latest_output),
    ]) == 0
    assert json.loads(latest_output.read_text(encoding="utf-8"))[
        "report_type"
    ] == "CHANGE_TRACKING_REPORT"
    assert main([
        "report", "export", "--run-id", str(refresh.run_id),
        "--report-id", str(report["id"]), "--format", "markdown",
        "--output", str(tmp_path / "invalid.md"),
    ]) == 64

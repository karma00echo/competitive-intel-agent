"""No paid calls: partial evidence, publication rollback and baseline isolation."""
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from competitive_intel.config import Settings, DatabaseSettings
from competitive_intel.domain.agent import AgentState
from competitive_intel.services.report_service import CompetitorReportService
from competitive_intel.web import create_app
from test_llm_fact_flow import seed, runner, Transport

pytestmark = pytest.mark.integration


def partial(p):
    seed(p)
    return runner(p, Transport(mode="partial")).run("Acme")


def test_partial_report_and_all_consumers_isolated(persistence):
    seed(persistence)
    first = runner(persistence, Transport()).run("Acme")
    result = runner(persistence, Transport(mode="partial"), model="new-policy").run("Acme")
    assert result.final_state == AgentState.PARTIAL_SUCCESS
    assert result.summary.report_type == "PARTIAL_EVIDENCE"
    with persistence.transaction() as tx:
        run = persistence.agent_runs.get(tx, result.run_id)
        cid = run["competitor_id"]
        assert run["status"] == "PARTIAL_SUCCESS"
        observations = persistence.fact_observations.list_for_run(tx, result.run_id)
        assert observations and all(f["comparison_status"] == "PENDING" for f in observations)
        baseline = persistence.agent_runs.get_previous_successful_with_facts(tx, cid, result.run_id + 1)
        assert baseline["id"] == first.run_id
        assert persistence.reports.get_latest_for_competitor(tx, cid)["id"] == first.summary.report_id
        assert persistence.dashboard.competitor_overview(tx, cid)["latest_report_id"] == first.summary.report_id
        assert not persistence.changes.list_for_run(tx, result.run_id)
        report = persistence.reports.get(tx, result.summary.report_id)
    content = json.loads(report["summary_json"])["content_json"]
    assert content["baseline_eligible"] is False
    assert content["failed_source_count"] == 1
    assert content["visible_fact_ids"]
    assert CompetitorReportService(persistence).get(run_id=result.run_id).report_type == "PARTIAL_EVIDENCE"
    from competitive_intel.services.fact_history_service import FactHistoryService
    from competitive_intel.domain.agent import RunMode
    with pytest.raises(ValueError, match='Incomplete'):
        FactHistoryService(persistence).establish_baseline(cid, result.run_id)
    with pytest.raises(ValueError, match='Incomplete'):
        FactHistoryService(persistence).compare_and_persist(cid, result.run_id, first.run_id)
    with pytest.raises(ValueError, match='Incomplete'):
        CompetitorReportService(persistence).generate(cid, result.run_id, RunMode.BASELINE)
    settings = Settings(database=DatabaseSettings("127.0.0.1", 3306, "unused_test", "unused", ""))
    with TestClient(create_app(settings=settings, persistence=persistence)) as client:
        data = client.get(f"/api/workspace/runs/{result.run_id}").json()["data"]
        assert data["run"]["final_state"] == "PARTIAL_SUCCESS"
        assert data["run"]["failed_source_count"] == 1
        assert data["report"]["report_type"] == "PARTIAL_EVIDENCE"
        assert all(f["observation_status"] == "PENDING" for f in data["facts"])
        detail = client.get(f"/api/reports/{result.summary.report_id}").json()["data"]
        assert detail["report_type"] == "PARTIAL_EVIDENCE"


@pytest.mark.parametrize("failure", ["report", "audit", "status", "extraction_audit"])
def test_publication_failure_rolls_back_and_marks_failed(persistence, monkeypatch, failure):
    if failure == "report":
        target, method = persistence.reports, "create"
    elif failure in {"audit", "extraction_audit"}:
        target, method = persistence.tool_calls, "finish"
    else:
        target, method = persistence.agent_runs, "finish"
    original = getattr(target, method)
    def injected(*args, **kwargs):
        output = kwargs.get("output_summary", {})
        hit = (failure == "report" and kwargs.get("report_type") == "PARTIAL_EVIDENCE"
               or failure == "status" and kwargs.get("status") == "PARTIAL_SUCCESS"
               or failure == "audit" and "partial_evidence" in output
               or failure == "extraction_audit" and "provider_calls" in output)
        if hit:
            raise RuntimeError("synthetic persistence failure")
        return original(*args, **kwargs)
    monkeypatch.setattr(target, method, injected)
    result = partial(persistence)
    assert result.final_state == AgentState.FAILED
    with persistence.transaction() as tx:
        assert persistence.agent_runs.get(tx, result.run_id)["status"] == "FAILED"
        assert persistence.reports.get_for_run(tx, result.run_id, "PARTIAL_EVIDENCE") is None
        assert not persistence.changes.list_for_run(tx, result.run_id)
        assert all(f["comparison_status"] == "PENDING"
                   for f in persistence.fact_observations.list_for_run(tx, result.run_id))
        assert not any("partial_evidence" in (c.get("output_summary") or "")
                       for c in persistence.tool_calls.list_for_run(tx, result.run_id))


def test_corrupt_source_reference_cannot_publish(persistence, monkeypatch):
    original = persistence.fact_observations.list_for_run
    def corrupted(*args):
        rows = original(*args)
        return [{**r, "source_id": -1} for r in rows]
    monkeypatch.setattr(persistence.fact_observations, "list_for_run", corrupted)
    result = partial(persistence)
    assert result.final_state == AgentState.FAILED
    assert "INVALID_PARTIAL_PROVENANCE" in result.errors[-1]


@pytest.mark.parametrize("mode", ["empty", "conflict"])
def test_no_publishable_evidence_remains_failed(persistence, mode):
    seed(persistence)
    result = runner(persistence, Transport(mode=mode)).run("Acme")
    assert result.final_state == AgentState.FAILED
    with persistence.transaction() as tx:
        assert not persistence.reports.get_for_run(tx, result.run_id, "PARTIAL_EVIDENCE")
        assert not persistence.changes.list_for_run(tx, result.run_id)
        calls = persistence.tool_calls.list_for_run(tx, result.run_id)
    if mode == "empty":
        extraction = next(json.loads(c["output_summary"]) for c in calls
                          if c["tool_name"] == "extract_competitor_facts")
        assert extraction["provider_calls"][0]["page_status"] == "NO_FACTS"
        assert "NO_UNCONTESTED_VERIFIED_FACTS" in result.errors[-1]


def test_mixed_conflict_excluded_but_uncontested_fact_publishable(persistence):
    from test_baseline_integrity import ManyTransport, ManyPage, provider
    from test_llm_fact_flow import Discovery
    from competitive_intel.services import AgentRunner, AgentToolExecutor, FactExtractionService, SnapshotService
    from competitive_intel.infrastructure.agent import FixtureAgentProvider
    seed(persistence)
    with persistence.transaction() as tx:
        cid = persistence.competitors.get_by_normalized_name(tx, "acme")["id"]
        persistence.sources.create(tx, competitor_id=cid, source_type="FEATURES",
            url="https://acme.example/features", normalized_url="https://acme.example/features",
            domain="acme.example", verification_status="VERIFIED", confidence=0.99,
            verified_at=datetime.now(UTC).replace(tzinfo=None))
    transport = ManyTransport(2)
    transport.conflict_second = True
    tools = AgentToolExecutor(persistence, Discovery(), SnapshotService(persistence, ManyPage()),
        FactExtractionService(persistence, provider(transport)), search_provider="serper",
        fetch_mode="real", fact_provider="openai_compatible")
    result = AgentRunner(persistence, FixtureAgentProvider(), tools).run("Acme")
    assert result.final_state == AgentState.PARTIAL_SUCCESS
    assert result.summary.confirmed_fact_count == 1
    report = CompetitorReportService(persistence).get(report_id=result.summary.report_id)
    assert report.content_json["excluded_conflict_keys"] == ["feature.feature0"]
    visible = report.content_json["sections"][2]["items"]
    assert [f["fact_key"] for f in visible] == ["feature.feature1"]
    assert report.content_json["sections"][5]["items"]
    with persistence.transaction() as tx:
        assert not persistence.fact_versions.list_current(tx, cid)
        assert not persistence.changes.list_for_run(tx, result.run_id)

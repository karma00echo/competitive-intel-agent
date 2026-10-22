"""Disposable MySQL + production HTTP adapters with synthetic transports only."""

from dataclasses import replace
import json
from pathlib import Path
import sys

import pytest
import requests
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from discovery_support import service, settings, spec
from competitive_intel.domain.task_budget import BudgetLimits, TaskBudget
from competitive_intel.persistence import Database, Persistence
from competitive_intel.persistence.repositories import _all
from competitive_intel.services.agent_runner import AgentRunner
from competitive_intel.web.app import create_app

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("Paid/live HTTP forbidden"))


@pytest.mark.parametrize("mode,expected", [("normal", "READY"), ("ambiguous", "NEEDS_CLARIFICATION"),
    ("search_failure", "PARTIAL"), ("model_failure", "PARTIAL"), ("unrelated", "PARTIAL")])
def test_persisted_discovery_survives_new_connection_and_never_publishes_history(persistence, mode, expected):
    with persistence.transaction() as tx:
        cid = persistence.competitors.create(tx, canonical_name="Existing", normalized_name="existing")
        rid = persistence.agent_runs.create(tx, input_name="Existing", normalized_input="existing", competitor_id=cid)
        persistence.agent_runs.finish(tx, rid, status="COMPLETED", current_state="COMPLETED")
        report_id = persistence.reports.create(tx, competitor_id=cid, run_id=rid, report_type="BASELINE",
            status="GENERATED", generator_version="test", content_markdown="Existing report remains intact")
        old_run = persistence.agent_runs.get(tx, rid)
        old_report = persistence.reports.get(tx, report_id)
    s, transport = service(mode=mode)
    result = AgentRunner.discover_competitors(persistence, spec(), s)
    assert result["status"] == expected
    fresh = Persistence(Database(engine=persistence.database.engine))
    with fresh.transaction() as tx:
        assert fresh.agent_runs.get(tx, rid) == old_run
        assert fresh.reports.get(tx, report_id) == old_report
        run = fresh.agent_runs.get(tx, result["run_id"])
        assert run["run_mode"] == "UNKNOWN" and run["competitor_id"] is None
        assert run["status"] == ("COMPLETED" if expected == "READY" else "PARTIAL_SUCCESS")
        calls = fresh.tool_calls.list_for_run(tx, result["run_id"])
        stored = json.loads(calls[0]["output_summary"])
        assert stored == result
        assert fresh.fact_observations.list_for_run(tx, result["run_id"]) == []
        assert fresh.changes.list_for_run(tx, result["run_id"]) == []
        assert fresh.snapshots.list_for_run(tx, result["run_id"]) == []
        assert _all(tx, "SELECT id FROM reports WHERE run_id=:id", {"id": result["run_id"]}) == []
        assert fresh.agent_runs.get_previous_successful_with_facts(tx, cid, result["run_id"] + 1) is None
    with TestClient(create_app(settings=settings(), persistence=fresh)) as client:
        view = client.get(f'/api/runs/{result["run_id"]}').json()["data"]
        assert view["analysis_complete"] is False and view["execution_phase"] == "competitor_discovery"
        assert view["provider_summary"]["search_provider"] == "serper"
        assert client.get(f'/api/analyst/discover/{result["run_id"]}').json()["data"] == result
        assert client.get(f'/api/analyst/discover/{rid}').status_code == 404


def test_budget_is_durable_before_http_and_partial_retains_verified_identity(persistence):
    s, transport = service(limits=replace(BudgetLimits(), searches=5))
    original = transport.post
    checked = []
    def inspect(url, **kwargs):
        with persistence.transaction() as tx:
            rows = _all(tx, "SELECT output_summary,finished_at,status FROM tool_calls WHERE tool_name='discover_competitors'", {})
            audit = json.loads(rows[0]["output_summary"])
            assert audit["budget"]["used"]["searches"] == s.context.budget.used["searches"]
            assert rows[0]["finished_at"] is None and rows[0]["status"] == "RUNNING"
            checked.append(True)
        return original(url, **kwargs)
    transport.post = inspect
    result = AgentRunner.discover_competitors(persistence, spec(), s)
    assert result["status"] == "PARTIAL" and result["target"]
    assert result["candidates"][0]["identity"]["name"] == "Birch"
    assert len(checked) == 5
    with persistence.transaction() as tx:
        audit = json.loads(persistence.tool_calls.list_for_run(tx, result["run_id"])[0]["output_summary"])
    ledger = TaskBudget.from_trusted_state(audit["budget"])
    assert ledger.exhausted == "searches" and ledger.used["searches"] == 5


@pytest.mark.parametrize("natural_language", [False, True])
def test_actual_api_entry_uses_same_runner_budget_and_persistence(persistence, monkeypatch, natural_language):
    import competitive_intel.api.competitor_discovery as endpoint
    s, _ = service()
    monkeypatch.setattr(endpoint, "ResearchContext", lambda *a, **kw: s.context)
    for key in ("RESEARCH_SEARCH_COST_MICROUSD", "RESEARCH_INPUT_COST_MICROUSD_PER_MILLION", "RESEARCH_OUTPUT_COST_MICROUSD_PER_MILLION"):
        monkeypatch.setenv(key, "1")
    payload = {"text": "分析 Atlas"} if natural_language else {"task": spec().model_dump()}
    payload["allow_paid"] = True  # Test transports only; network guard above.
    with TestClient(create_app(settings=settings(), persistence=persistence)) as client:
        response = client.post("/api/analyst/discover", json=payload)
        assert response.status_code == 200, response.text
        result = response.json()["data"]
        assert result["selected"] == ["Birch", "Cedar"]
        assert result["budget"]["used"]["understanding"] == int(natural_language)
        assert client.get(f'/api/runs/{result["run_id"]}').status_code == 200


def test_checkpoint_failure_prevents_external_attempt(persistence, monkeypatch):
    s, transport = service()
    monkeypatch.setattr(persistence.tool_calls, "checkpoint", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("private details")))
    result = AgentRunner.discover_competitors(persistence, spec(competitors=["Birch"], discover_competitors=False), s)
    assert result["status"] == "FAILED" and transport.calls == []
    assert result["selected"] == ["Birch"]
    assert "private details" not in json.dumps(result)


def test_explicit_candidates_preserved_through_api_and_database(persistence, monkeypatch):
    import competitive_intel.api.competitor_discovery as endpoint
    s, transport = service(limits=replace(BudgetLimits(), searches=0))
    monkeypatch.setattr(endpoint, "ResearchContext", lambda *a, **kw: s.context)
    for key in ("RESEARCH_SEARCH_COST_MICROUSD", "RESEARCH_INPUT_COST_MICROUSD_PER_MILLION", "RESEARCH_OUTPUT_COST_MICROUSD_PER_MILLION"):
        monkeypatch.setenv(key, "1")
    task = spec(competitors=["Birch"], discover_competitors=False)
    with TestClient(create_app(settings=settings(), persistence=persistence)) as client:
        result = client.post("/api/analyst/discover", json={"task": task.model_dump(), "allow_paid": True}).json()["data"]
    assert result["status"] == "PARTIAL" and result["selected"] == ["Birch"]
    assert transport.calls == []

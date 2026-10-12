"""Real adapter + mocked HTTPS transport + disposable MySQL; never paid requests."""
import json
from datetime import UTC, datetime
from unittest.mock import Mock
from types import SimpleNamespace
import pytest

from fastapi.testclient import TestClient

from competitive_intel.api.schemas import AnalysisRequest
from competitive_intel.config import LLMSettings, Settings, DatabaseSettings
from competitive_intel.domain.agent import AgentState
from competitive_intel.domain.webpage import FetchPageResult, FetchStatus
from competitive_intel.infrastructure.agent import FixtureAgentProvider
from competitive_intel.infrastructure.facts.llm_provider import LLMFactExtractionProvider
from competitive_intel.services import AgentRunner, AgentToolExecutor, FactExtractionService, SnapshotService
from competitive_intel.web import create_app
from competitive_intel.web.runtime import build_runner


TEXT = "Acme Docs lets teams edit documents together."


class Page:
    def fetch(self, request):
        return FetchPageResult(request.url, request.url, (request.url,), 200, "text/html",
                               "Acme", f"<html><body><main><p>{TEXT}</p></main></body></html>",
                               datetime.now(UTC).replace(tzinfo=None), FetchStatus.SUCCESS)


class Discovery:
    def __init__(self, *args):
        pass

    def discover(self, *args, **kwargs):
        return SimpleNamespace(identity=SimpleNamespace(normalized_name="acme"),provider="mock-search",
            candidates=[],official_domain="acme.example",pending=[],rejected=[],domain_evidence=[],warnings=[],errors=[])


class Transport:
    def __init__(self, bad=False, null_fields=False):
        self.count = 0
        self.bad = bad
        self.null_fields = null_fields

    def post(self, url, **kwargs):
        self.count += 1
        snapshot_id = json.loads(kwargs["json"]["messages"][1]["content"])["snapshot_id"]
        payload = {"snapshot_id":snapshot_id,"facts":[{
            "fact_category":"FEATURE", "fact_value":{
                "feature_name":"Docs","normalized_feature_name":"Docs",
                "feature_description":TEXT,"feature_category":"OTHER",
                "availability":None,"related_plan":None,"status":"UNKNOWN"},
            "evidence_text":"invented" if self.bad else TEXT,"confidence":0.9}]}
        if self.null_fields:
            payload["facts"][0]["fact_value"].update(status=None, feature_category=None)
        data = {"choices":[{"finish_reason":"stop","message":{"content":json.dumps(payload)}}],
                "usage":{"prompt_tokens":100,"completion_tokens":50,"total_tokens":150}}
        response = Mock(status_code=200)
        response.iter_content.return_value = [json.dumps(data).encode()]
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        return context


def seed(persistence):
    with persistence.transaction() as session:
        competitor = persistence.competitors.create(session,canonical_name="Acme",normalized_name="acme",official_domain="acme.example")
        persistence.sources.create(session,competitor_id=competitor,source_type="FEATURES",
            url="https://acme.example/product",normalized_url="https://acme.example/product",
            domain="acme.example",verification_status="VERIFIED",confidence=0.99,
            verified_at=datetime.now(UTC).replace(tzinfo=None))


def runner(persistence, transport, model="test-model"):
    provider = LLMFactExtractionProvider(LLMSettings(api_key="test-only",model=model,
        endpoint="https://model.example/v1/chat/completions"),session=transport)
    tools = AgentToolExecutor(persistence,Discovery(),SnapshotService(persistence,Page()),
        FactExtractionService(persistence,provider),search_provider="serper",fetch_mode="real",
        fact_provider="openai_compatible")
    return AgentRunner(persistence,FixtureAgentProvider(),tools)


def test_same_clean_snapshot_reuses_audited_facts_without_second_model_call(persistence):
    seed(persistence)
    transport = Transport()
    first = runner(persistence,transport).run("Acme")
    assert first.final_state in {AgentState.COMPLETED,AgentState.COMPLETED_WITH_WARNINGS}
    assert first.summary.confirmed_fact_count == 1
    second = runner(persistence,transport).run("Acme")
    assert second.summary.unchanged_count == 1
    assert second.summary.modified_count == second.summary.added_count == second.summary.removed_count == 0
    assert transport.count == 1
    with persistence.transaction() as session:
        observed = persistence.fact_observations.list_for_run(session,second.run_id)
        calls = persistence.tool_calls.list_for_run(session,second.run_id)
        prior = persistence.fact_observations.list_for_run(session,first.run_id)
    assert observed[0]["observed_snapshot_id"] != prior[0]["observed_snapshot_id"]
    assert observed[0]["id"] == prior[0]["id"]
    payload = next(json.loads(c["output_summary"]) for c in calls if c["tool_name"] == "extract_competitor_facts")
    assert payload["provider_calls"][0]["reused"] is True
    assert payload["provider_calls"][0]["usage"] == {}
    # A different configured model cannot consume an old-model cache.
    runner(persistence,transport,model="different-model").run("Acme")
    assert transport.count == 2


def test_invalid_real_response_fails_run_without_facts_changes_report(persistence):
    seed(persistence)
    result = runner(persistence,Transport(bad=True)).run("Acme")
    assert result.final_state == AgentState.FAILED
    with persistence.transaction() as session:
        assert not persistence.fact_observations.list_for_run(session,result.run_id)
        assert not persistence.changes.list_for_run(session,result.run_id)
        calls = persistence.tool_calls.list_for_run(session,result.run_id)
    assert not any(c["tool_name"] == "generate_competitor_report" for c in calls)
    settings = Settings(database=DatabaseSettings("127.0.0.1",3306,"unused_test","unused",""))
    with TestClient(create_app(settings=settings,persistence=persistence)) as client:
        data = client.get(f"/api/workspace/runs/{result.run_id}").json()["data"]
        assert data["provider_summary"]["fact_provider"] == "openai_compatible"
        assert data["fact_extraction_status"] == "FAILED"
        assert data["run"]["fact_provider_calls"][0]["error_code"] == "EVIDENCE_NOT_FOUND"
        diagnostic = data["run"]["fact_provider_calls"][0]["evidence_diagnostics"][0]
        assert diagnostic["fact_index"] == 0
        assert diagnostic["field_name"] == "evidence_text"
        assert diagnostic["failure_type"] == "EVIDENCE_NOT_IN_SNAPSHOT"
        assert diagnostic["source_id"] > 0 and diagnostic["snapshot_id"] > 0
        assert "test-only" not in json.dumps(data)


def test_runtime_selects_real_provider_and_no_fixture_fallback(persistence,monkeypatch):
    seed(persistence)
    settings = Settings(database=DatabaseSettings("127.0.0.1",3306,"unused_test","unused",""))
    monkeypatch.setattr("competitive_intel.web.runtime.RequestsFetcher",Page)
    monkeypatch.setattr("competitive_intel.web.runtime.create_search_provider",lambda *a,**kw: SimpleNamespace(name="serper"))
    monkeypatch.setattr("competitive_intel.web.runtime.SourceDiscoveryService",Discovery)
    request = AnalysisRequest(competitor_name="Acme",search_provider="serper",fact_provider="openai_compatible")
    result = build_runner(settings,persistence,request,lambda _:None).run("Acme")
    assert result.final_state == AgentState.FAILED
    with persistence.transaction() as session:
        assert not persistence.fact_observations.list_for_run(session,result.run_id)


def test_provider_switch_rebaselines_without_fake_changes(persistence):
    seed(persistence)
    first = runner(persistence,Transport()).run("Acme")
    # Simulate a previously audited fixture baseline, using only repository writes.
    with persistence.transaction() as session:
        calls = persistence.tool_calls.list_for_run(session, first.run_id)
        for call in calls:
            payload = json.loads(call["output_summary"]) if call["output_summary"] else {}
            if call["tool_name"] in {"get_competitor_profile", "extract_competitor_facts", "finalize_run_summary"}:
                target = payload.get("summary",payload)
                target["fact_provider"] = "fixture"
                payload.pop("provider_calls",None)
                persistence.tool_calls.finish(session,call["id"],status="SUCCEEDED",output_summary=payload)
    second = runner(persistence,Transport()).run("Acme")
    assert second.summary.report_type == "BASELINE_REPORT"
    assert second.summary.modified_count == second.summary.removed_count == 0
    with persistence.transaction() as session:
        assert not persistence.changes.list_for_run(session,second.run_id)
        a = persistence.fact_observations.list_for_run(session,first.run_id)
        b = persistence.fact_observations.list_for_run(session,second.run_id)
    assert a[0]["id"] != b[0]["id"]


def test_single_source_extraction_persists_audit_without_changes(persistence):
    seed(persistence)
    with persistence.transaction() as session:
        competitor = persistence.competitors.get_by_normalized_name(session, "acme")
        source = persistence.sources.list_verified(session, competitor["id"])[0]
        other_id = persistence.sources.create(session, competitor_id=competitor["id"],
            source_type="FEATURES", url="https://acme.example/other",
            normalized_url="https://acme.example/other", domain="acme.example",
            verification_status="VERIFIED", confidence=0.99,
            verified_at=datetime.now(UTC).replace(tzinfo=None))
        run_id = persistence.agent_runs.create(session, competitor_id=competitor["id"],
            input_name="Acme", normalized_input="acme", run_mode="BASELINE", current_state="PAGE_FETCHING")
    for source_id in (source["id"], other_id):
        SnapshotService(persistence, Page()).process(source_id=source_id, run_id=run_id)
    transport = Transport()
    provider = LLMFactExtractionProvider(LLMSettings(api_key="test-only", model="test-model",
        endpoint="https://model.example", max_calls=1, max_retries=0), session=transport)
    service = FactExtractionService(persistence, provider)
    result = service.extract("Acme", source_id=source["id"])
    assert transport.count == 1
    assert len(result.saved) == 1
    assert not result.errors
    assert result.source_ids == (source["id"],)
    with persistence.transaction() as session:
        assert not persistence.changes.list_for_run(session, result.run_id)
        calls = persistence.tool_calls.list_for_run(session, result.run_id)
    audit = json.loads(calls[0]["output_summary"])["provider_calls"][0]["http_audit"][0]
    assert audit["http_status"] == 200
    assert audit["endpoint_path"] == "/chat/completions"
    with pytest.raises(ValueError, match="verified"):
        service.extract("Acme", source_id=-1)


def test_null_feature_fields_persist_as_audited_legacy_sentinels(persistence):
    seed(persistence)
    result = runner(persistence, Transport(null_fields=True)).run("Acme")
    assert result.summary.confirmed_fact_count == 1
    with persistence.transaction() as session:
        facts = persistence.product_facts.list_for_run(session, result.run_id)
        calls = persistence.tool_calls.list_for_run(session, result.run_id)
    value = json.loads(facts[0]["fact_value"])
    assert value["status"] == "UNKNOWN" and value["feature_category"] == "OTHER"
    assert facts[0]["evidence_status"] == "CONFIRMED"
    output = next(json.loads(c["output_summary"]) for c in calls if c["tool_name"] == "extract_competitor_facts")
    adaptations = output["provider_calls"][0]["contract_adaptations"]
    assert len(adaptations) == 2
    assert all(a["model_value"] is None and a["source_id"] > 0 for a in adaptations)

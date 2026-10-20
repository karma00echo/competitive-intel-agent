import json
import pytest
from dataclasses import replace
from unittest.mock import Mock

from competitive_intel.config import LLMSettings
from competitive_intel.infrastructure.facts.llm_provider import LLMFactExtractionProvider
from competitive_intel.services import FactExtractionService, SnapshotService
from test_llm_fact_flow import seed, Page, Transport, runner


TEXT = " ".join(f"Feature{i} supports workflow{i}." for i in range(7))


class ManyPage(Page):
    def fetch(self, request):
        return replace(super().fetch(request), raw_html=f"<html><main>{TEXT}</main></html>")


class ManyTransport(Transport):
    def __init__(self, count):
        super().__init__()
        self.fact_count = count

    def post(self, url, **kwargs):
        self.count += 1
        sid = json.loads(kwargs["json"]["messages"][1]["content"])["snapshot_id"]
        facts = [{"fact_category":"FEATURE", "fact_value":{
            "feature_name":f"Feature{i}", "normalized_feature_name":f"Feature{i}",
            "feature_description":f"supports workflow{i}.", "feature_category":None,
            "status":None, "availability":None,"related_plan":None},
            "evidence_text":f"Feature{i} supports workflow{i}.", "confidence":0.9}
            for i in range(self.fact_count)]
        if getattr(self, "conflict_second", False) and self.count == 2:
            facts[0]["fact_value"]["feature_description"] = "workflow0."
        response = Mock(status_code=200)
        response.iter_content.return_value = [json.dumps({"choices":[{"finish_reason":"stop",
            "message":{"content":json.dumps({"snapshot_id":sid,"facts":facts})}}]}).encode()]
        context = Mock()
        context.__enter__ = Mock(return_value=response)
        context.__exit__ = Mock(return_value=False)
        return context


def provider(transport, model="cache-test"):
    return LLMFactExtractionProvider(LLMSettings(api_key="test-only",model=model,
        endpoint="https://model.example/chat/completions"),session=transport)


def test_complete_cache_includes_five_existing_and_two_new(persistence):
    seed(persistence)
    with persistence.transaction() as tx:
        c = persistence.competitors.get_by_normalized_name(tx,"acme")
        source = persistence.sources.list_verified(tx,c["id"])[0]
        run_id = persistence.agent_runs.create(tx, competitor_id=c["id"], input_name="Acme", normalized_input="acme")
    SnapshotService(persistence,ManyPage()).process(source_id=source["id"], run_id=run_id)
    first = FactExtractionService(persistence,provider(ManyTransport(5),"old-policy")).extract("Acme")
    seven = ManyTransport(7)
    second = FactExtractionService(persistence,provider(seven)).extract("Acme")
    assert not second.errors and len(second.saved) == 7
    with persistence.transaction() as tx:
        rows = persistence.fact_observations.list_for_run(tx,second.run_id)
    assert sum(row["run_id"] == second.run_id for row in rows) == 2
    assert second.duplicate_count == 5
    with persistence.transaction() as tx:
        run_id = persistence.agent_runs.create(tx, competitor_id=c["id"], input_name="Acme", normalized_input="acme")
    SnapshotService(persistence,ManyPage()).process(source_id=source["id"], run_id=run_id)
    third = FactExtractionService(persistence,provider(seven)).extract("Acme")
    assert not third.errors and len(third.saved) == 7 and seven.count == 1
    assert third.provider_calls[0]["reused"]
    assert {f.fact_key for f in third.saved} == {f.fact_key for f in second.saved}


def test_formal_baseline_excludes_smoke_and_pending(persistence):
    seed(persistence)
    formal = runner(persistence,Transport()).run("Acme")
    smoke = FactExtractionService(persistence,provider(Transport(),"smoke")).extract("Acme")
    with persistence.transaction() as tx:
        c = persistence.competitors.get_by_normalized_name(tx,"acme")
        selected = persistence.agent_runs.get_previous_successful_with_facts(tx,c["id"],smoke.run_id+1)
        assert selected["id"] == formal.run_id
        observations = persistence.fact_observations.list_for_run(tx,formal.run_id)
        persistence.fact_observations.update_status(tx,formal.run_id,observations[0]["id"],"PENDING")
        assert persistence.agent_runs.get_previous_successful_with_facts(tx,c["id"],smoke.run_id+1) is None


def test_empty_page_cache_is_not_a_baseline(persistence):
    seed(persistence)
    with persistence.transaction() as tx:
        c = persistence.competitors.get_by_normalized_name(tx,"acme")
        source = persistence.sources.list_verified(tx,c["id"])[0]
        run_id = persistence.agent_runs.create(tx, competitor_id=c["id"],input_name="Acme",normalized_input="acme")
    SnapshotService(persistence,ManyPage()).process(source_id=source["id"],run_id=run_id)
    transport = ManyTransport(0)
    a = FactExtractionService(persistence,provider(transport)).extract("Acme")
    b = FactExtractionService(persistence,provider(transport)).extract("Acme")
    assert not a.errors and not b.errors and not b.saved and transport.count == 1
    assert b.provider_calls[0]["page_status"] == "NO_FACTS" and b.provider_calls[0]["reused"]


@pytest.mark.parametrize("conflict", [False, True])
def test_duplicate_sources_keep_complete_independent_caches(persistence, conflict):
    seed(persistence)
    from datetime import UTC, datetime
    with persistence.transaction() as tx:
        c = persistence.competitors.get_by_normalized_name(tx,"acme")
        other = persistence.sources.create(tx,competitor_id=c["id"],source_type="FEATURES",
            url="https://acme.example/other",normalized_url="https://acme.example/other",
            domain="acme.example",verification_status="VERIFIED",confidence=0.99,
            verified_at=datetime.now(UTC).replace(tzinfo=None))
        sources = persistence.sources.list_verified(tx,c["id"])
        run_id = persistence.agent_runs.create(tx,competitor_id=c["id"],input_name="Acme",normalized_input="acme")
    for source in sources:
        SnapshotService(persistence,ManyPage()).process(source_id=source["id"],run_id=run_id)
    transport = ManyTransport(7)
    transport.conflict_second = conflict
    a = FactExtractionService(persistence,provider(transport)).extract("Acme")
    if conflict:
        assert a.errors and "cache_key" not in a.provider_calls[1]
        with persistence.transaction() as tx:
            assert all(row["comparison_status"] == "PENDING"
                       for row in persistence.fact_observations.list_for_run(tx,a.run_id))
        return
    assert not a.errors and a.duplicate_count == 7
    assert [len(call["validated_facts"]) for call in a.provider_calls] == [7,7]
    b = FactExtractionService(persistence,provider(transport)).extract("Acme",source_id=other)
    assert not b.errors and len(b.saved) == 7 and transport.count == 2
    assert b.provider_calls[0]["reused"]
    with persistence.transaction() as tx:
        rows = persistence.fact_observations.list_for_run(tx,b.run_id)
        assert all(row["source_id"] == other for row in rows)


def test_cache_evidence_is_checked_against_snapshot(persistence):
    seed(persistence)
    first = runner(persistence,Transport()).run("Acme")
    with persistence.transaction() as tx:
        calls = persistence.tool_calls.list_for_run(tx,first.run_id)
        call = next(c for c in calls if c["tool_name"] == "extract_competitor_facts")
        payload = json.loads(call["output_summary"])
        payload["provider_calls"][0]["validated_facts"][0]["evidence_text"] = "not in snapshot"
        persistence.tool_calls.finish(tx,call["id"],status="SUCCEEDED",output_summary=payload)
    transport = Transport()
    result = runner(persistence,transport).run("Acme")
    assert result.final_state.value == "FAILED" and transport.count == 0
    with persistence.transaction() as tx:
        assert not persistence.fact_observations.list_for_run(tx,result.run_id)
        assert not persistence.changes.list_for_run(tx,result.run_id)


def test_partial_result_does_not_enter_complete_cache(persistence):
    seed(persistence)
    with persistence.transaction() as tx:
        c = persistence.competitors.get_by_normalized_name(tx,"acme")
        source = persistence.sources.list_verified(tx,c["id"])[0]
        rid = persistence.agent_runs.create(tx,competitor_id=c["id"],input_name="Acme",normalized_input="acme")
    SnapshotService(persistence,Page()).process(source_id=source["id"],run_id=rid)
    good = FactExtractionService(persistence,provider(Transport())).extract("Acme")
    bad = FactExtractionService(persistence,provider(Transport(mode="partial"),"partial-policy")).extract("Acme")
    assert bad.errors and "cache_key" not in bad.provider_calls[0]
    with persistence.transaction() as tx:
        rows = persistence.fact_observations.list_for_run(tx,bad.run_id)
        assert rows and all(r["comparison_status"] == "PENDING" for r in rows)


def test_only_smoke_history_starts_formal_baseline_not_comparison(persistence):
    seed(persistence)
    with persistence.transaction() as tx:
        c = persistence.competitors.get_by_normalized_name(tx,"acme")
        source = persistence.sources.list_verified(tx,c["id"])[0]
        rid = persistence.agent_runs.create(tx,competitor_id=c["id"],input_name="Acme",normalized_input="acme")
    SnapshotService(persistence,Page()).process(source_id=source["id"],run_id=rid)
    FactExtractionService(persistence,provider(Transport())).extract("Acme")
    result = runner(persistence,Transport()).run("Acme")
    assert result.summary.report_type == "BASELINE_REPORT"
    with persistence.transaction() as tx:
        assert not persistence.changes.list_for_run(tx,result.run_id)

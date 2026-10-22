"""Offline tests: all external provider transports are replaced, not live accuracy."""

from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import sys
from pathlib import Path

import pytest
import requests
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from discovery_support import Response, Transport, service, settings, spec
from competitive_intel.api.competitor_discovery import router
from competitive_intel.domain.task_budget import BudgetLimits, TaskBudget, BudgetExhausted
from competitive_intel.infrastructure.budgeted_transport import BudgetedSession, CostRates
from competitive_intel.services.research_context import ResearchContext
from competitive_intel.services.task_understanding_service import TaskUnderstandingService


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("Real network forbidden"))


def test_discovery_uses_real_adapters_with_mock_http_and_bounded_nominees():
    s, t = service()
    result = s.discover(spec())
    assert result["status"] == "READY", result["issues"]
    assert result["selected"] == ["Birch", "Cedar"]
    assert len(result["candidates"]) == 3
    assert result["analysis_complete"] is False and result["report_id"] is None
    assert result["budget"]["used"]["searches"] == 9
    assert result["budget"]["used"]["evaluation"] == 1
    for candidate in result["candidates"]:
        assert candidate["identity"]["collected_at"]
        assert candidate["identity"]["content_sha256"]
        assert candidate["relevance"]["candidate_quote"] in candidate["identity"]["content"]
        assert candidate["selection"] == "EVIDENCE_BASED_INFERENCE"


def test_explicit_scope_is_preserved_without_alternatives_or_model_evaluation():
    s, t = service()
    result = s.discover(spec(competitors=["Birch"], discover_competitors=False, intent="comparison"))
    assert result["status"] == "READY"
    assert result["selected"] == ["Birch"]
    assert result["budget"]["used"]["models"] == 0
    assert not any("alternatives" in call[2].get("q", "") for call in t.calls if call[0] == "post")


@pytest.mark.parametrize("mode", ["search_failure", "page_failure", "model_failure", "unrelated"])
def test_failures_are_incomplete_not_fabricated_competitors(mode):
    s, _ = service(mode=mode)
    result = s.discover(spec())
    assert result["status"] in {"PARTIAL", "NEEDS_CLARIFICATION"}
    assert result["selected"] == []
    assert result["issues"]


def test_ambiguous_target_does_not_select_first_result():
    s, _ = service(mode="ambiguous")
    result = s.discover(spec())
    assert result["status"] == "NEEDS_CLARIFICATION"
    assert result["target"] is None and not result["selected"]


def test_duplicate_and_target_nominees_are_not_rechecked():
    s, _ = service(candidates=("Atlas", "Birch", "BIRCH", "Cedar"))
    result = s.discover(spec())
    assert result["selected"] == ["Birch", "Cedar"]
    assert len(result["candidates"]) == 2


def test_no_hardcoded_brands_names_come_from_article_links():
    s, _ = service(mode="article", candidates=("Quasar", "Meadow"))
    result = s.discover(spec())
    assert result["selected"] == ["Quasar", "Meadow"]
    assert all(c["discovered_from"]["kind"] == "external_link_lead_not_identity_proof" for c in result["candidates"])


@pytest.mark.parametrize("mode", ["fabricated_quote", "invented_name"])
def test_invalid_model_evidence_is_rejected_without_losing_other_valid_candidates(mode):
    s, _ = service(mode=mode)
    result = s.discover(spec())
    assert "Birch" not in result["selected"]
    assert result["selected"] == ["Cedar", "Dune"]
    assert result["status"] == "PARTIAL"


def test_insufficient_candidates_disclosed():
    s, _ = service(candidates=("Birch",))
    result = s.discover(spec())
    assert result["status"] == "PARTIAL" and result["selected"] == ["Birch"]


@pytest.mark.parametrize("resource,limit", [("searches", 5), ("fetches", 2), ("evaluation", 0), ("tokens", 10), ("cost_microusd", 0)])
def test_budget_exhaustion_preserves_collected_evidence_and_stops(resource, limit):
    s, transport = service(limits=replace(BudgetLimits(), **{resource: limit}))
    result = s.discover(spec())
    assert result["status"] == "PARTIAL"
    assert result["budget"]["exhausted"] == resource
    assert result["budget"]["used"][resource] <= limit
    count = len(transport.calls)
    with pytest.raises(BudgetExhausted): s.context.session("searches").post("https://search.example", json={})
    assert len(transport.calls) == count
    if resource == "evaluation": assert len(result["candidates"]) == 3 and result["evidence"]


def test_explicit_scope_survives_zero_budget():
    s, _ = service(limits=replace(BudgetLimits(), searches=0))
    result = s.discover(spec(competitors=["Birch", "Cedar"], discover_competitors=False))
    assert result["selected"] == ["Birch", "Cedar"]
    assert all(c["status"] == "UNVERIFIED" for c in result["candidates"])


def test_understanding_discovery_and_later_model_transports_share_one_ledger():
    s, transport = service()
    interpreted = TaskUnderstandingService(s.context.understanding_provider()).interpret("分析 Atlas")
    assert interpreted["status"] == "READY"
    result = s.discover(spec())
    assert result["budget"]["used"]["models"] == 2
    ledger = TaskBudget.from_trusted_state(result["budget"])
    assert ledger.task_id == s.context.budget.task_id
    context = ResearchContext(settings(), allow_paid=True, budget=ledger, session_factory=lambda p: transport)
    for _ in range(10):
        context.session("extraction").post("https://models.example", json={"max_tokens": 1, "messages": [{"content": '{"request":"analysis"}'}]})
    with pytest.raises(BudgetExhausted):
        context.session("extraction").post("https://models.example", json={"max_tokens": 1})
    assert ledger.used["extraction"] == 10
    assert ledger.used["models"] == 12


def test_no_implicit_paid_permission():
    context = ResearchContext(settings())
    with pytest.raises(PermissionError): context.search_provider()
    assert not any(context.budget.used.values())
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/api/analyst/discover", json={"task": spec().model_dump()})
    assert response.status_code == 403


def test_single_product_and_clarification_never_nominate():
    s, _ = service()
    result = s.discover(spec(intent="product_analysis", discover_competitors=False))
    assert result["status"] == "READY" and result["selected"] == []
    s, _ = service()
    result = s.discover(spec(status="NEEDS_CLARIFICATION", target=None, clarification="Which product?"))
    assert result["status"] == "NEEDS_CLARIFICATION" and not any(result["budget"]["used"].values())


def test_redirect_hops_charge_before_network_and_close_intermediate_response():
    class Redirects:
        def __init__(self): self.responses = []
        def get(self, url, **kwargs):
            response = Response(url=url, status=302, headers={"Location": "/next"})
            self.responses.append(response); return response
    raw = Redirects(); ledger = TaskBudget(replace(BudgetLimits(), fetches=2))
    session = BudgetedSession(ledger, "fetches", session=raw)
    with pytest.raises(BudgetExhausted): session.get("https://public.example/")
    assert len(raw.responses) == 2 and all(r.closed for r in raw.responses)


def test_concurrent_budget_reservations_cannot_overspend():
    ledger = TaskBudget(replace(BudgetLimits(), searches=3))
    def attempt(_):
        try: ledger.reserve(searches=1); return True
        except BudgetExhausted: return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(20))) == 3


def test_failed_model_attempt_is_charged_and_unknown_usage_not_refunded():
    class Failure:
        def post(self, *args, **kwargs): raise requests.Timeout("test")
    ledger = TaskBudget()
    transport = BudgetedSession(ledger, "evaluation", session=Failure())
    with pytest.raises(requests.Timeout): transport.post("https://model.example", json={"max_tokens": 100})
    assert ledger.used["models"] == 1 and ledger.used["tokens"] >= 1124
    with pytest.raises(BudgetExhausted): transport.post("https://model.example", json={"max_tokens": 100})


def test_same_page_evidence_is_reused_without_second_fetch():
    s, transport = service()
    first = s._page("https://atlas.example/")
    second = s._page("https://atlas.example/")
    assert first == second and s.context.budget.used["fetches"] == 1


@pytest.mark.parametrize("quote,use", [
    ("Atlas and Birch document collaboration products are mentioned together.", "document collaboration"),
    ("Birch provides software for teams.", "for teams"),
    ("Birch does not support document collaboration.", "document collaboration"),
])
def test_cooccurrence_generic_and_negative_evidence_are_not_competition(quote, use):
    from competitive_intel.infrastructure.agent.candidate_evaluation import Relevance
    from competitive_intel.services.competitor_discovery import CompetitorDiscoveryService
    target = {"name": "Atlas", "content": "Atlas provides document collaboration software for teams."}
    candidate = {"name": "Birch", "content": quote}
    item = Relevance(name="Birch", target_quote=target["content"], candidate_quote=quote, shared_use=use)
    assert not CompetitorDiscoveryService._grounded(item, target, candidate)


def test_later_fact_provider_instances_do_not_reset_task_budget():
    from competitive_intel.infrastructure.facts.base import FactExtractionRequest
    from competitive_intel.domain.facts import FactCategory
    import json
    class EmptyFacts:
        calls = 0
        def post(self, url, **kwargs):
            self.calls += 1
            data = json.loads(kwargs["json"]["messages"][-1]["content"])
            return Response({"choices": [{"finish_reason": "stop", "message": {
                "content": json.dumps({"snapshot_id": data["snapshot_id"], "facts": []})}}]})
        def close(self): pass
    raw = EmptyFacts()
    context = ResearchContext(settings(), allow_paid=True, budget=TaskBudget(replace(BudgetLimits(), extraction=1)),
                              session_factory=lambda purpose: raw)
    first, second = context.fact_provider(), context.fact_provider()
    request = FactExtractionRequest("Atlas", "FEATURES", "https://atlas.example/", 1,
                                   "Atlas provides document collaboration.", (FactCategory.FEATURE,), {}, 5)
    assert first.extract(request).page_status == "NO_FACTS"
    with pytest.raises(BudgetExhausted): second.extract(replace(request, competitor_name="Birch", snapshot_id=2))
    assert raw.calls == 1


def test_trusted_handoff_preserves_rates_counters_and_rejects_model_change():
    s, transport = service()
    audit = s.discover(spec())
    context = ResearchContext.from_trusted_audit(settings(), audit, allow_paid=True, session_factory=lambda purpose: transport)
    assert context.budget.snapshot() == audit["budget"]
    assert context.rates == s.context.rates
    with pytest.raises(ValueError):
        ResearchContext.from_trusted_audit(replace(settings(), llm=replace(settings().llm, model="different")), audit)


def test_cost_configuration_required_before_live_api(monkeypatch):
    for key in ("RESEARCH_SEARCH_COST_MICROUSD", "RESEARCH_INPUT_COST_MICROUSD_PER_MILLION", "RESEARCH_OUTPUT_COST_MICROUSD_PER_MILLION"):
        monkeypatch.delenv(key, raising=False)
    app = FastAPI(); app.include_router(router)
    with TestClient(app) as client:
        response = client.post("/api/analyst/discover", json={"text": "分析 Atlas", "allow_paid": True})
    assert response.status_code == 503

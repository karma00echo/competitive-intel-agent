"""Real production adapters with injected synthetic HTTP; not real E2E acceptance."""
import json
import subprocess
import time
import pytest
import requests
from fastapi.testclient import TestClient

from tests.discovery_support import Response, Transport, settings, spec
from competitive_intel.domain.task_budget import TaskBudget, BudgetLimits
from competitive_intel.services.research_context import ResearchContext
from competitive_intel.services.agent_runner import AgentRunner
from competitive_intel.web.app import create_app

pytestmark = pytest.mark.integration


class WorkflowTransport(Transport):
    def __init__(self, *, auto=False, mode="normal"):
        super().__init__()
        self.auto, self.workflow_mode = auto, mode

    def post(self, url, **kwargs):
        payload = kwargs["json"]
        if "q" in payload:
            if '"' not in payload["q"]:
                name = payload["q"].split()[0]
                self.calls.append(("post", url, payload))
                return Response({"organic": [{"title": name + " " + path, "link": f"https://{name.lower()}.example/{path}",
                    "snippet": name + " official product", "position": i + 1} for i, path in enumerate(["", "features", "pricing"])]})
            return super().post(url, **kwargs)
        data = json.loads(payload["messages"][-1]["content"])
        if "request" in data:
            answer = spec(competitors=[] if self.auto else ["Birch"], discover_competitors=self.auto,
                          dimensions=["core_features", "pricing"]).model_dump()
            if self.workflow_mode == "complete":
                answer["dimensions"] = ["core_features"]
            if self.workflow_mode == "two_rivals":
                answer["competitors"] = ["Birch", "Cedar"]
                answer["dimensions"] = ["core_features"]
            if self.workflow_mode == "clarify":
                answer.update(status="NEEDS_CLARIFICATION", clarification="Which product?", target=None, competitors=[], discover_competitors=False)
        elif "snapshot_id" in data:
            if self.workflow_mode == "model_failure":
                return Response({}, status=503)
            quote = "document collaboration for teams"
            answer = {"snapshot_id": data["snapshot_id"], "facts": [{"fact_category": "FEATURE",
                "fact_value": {"feature_name": "document collaboration", "normalized_feature_name": "document collaboration",
                    "feature_description": quote, "feature_category": "OTHER", "availability": None, "related_plan": None, "status": "UNKNOWN"},
                "evidence_text": quote, "confidence": 0.9}]}
            if data["source_type"] == "PRICING":
                answer["facts"] = []
        elif "findings" in data:
            answer = {"selected_finding_ids": [data["findings"][0]["id"]]}
        else:
            return super().post(url, **kwargs)
        self.calls.append(("model", url, data))
        return Response({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                         "usage": {"prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200}})


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("Live HTTP forbidden"))


def context(*, auto=False, mode="normal", limits=None):
    transport = WorkflowTransport(auto=auto, mode=mode)
    return ResearchContext(settings(), allow_paid=True, budget=TaskBudget(limits), session_factory=lambda _: transport), transport


@pytest.mark.parametrize("auto", [False, True])
def test_full_workflow_uses_real_adapters_and_preserves_partial_evidence(persistence, auto):
    ctx, transport = context(auto=auto)
    flow = AgentRunner.workflow(persistence, ctx)
    text = "Analyze Atlas" if auto else "Compare Atlas and Birch features and pricing"
    handles = flow.prepare(text)
    result = flow.execute(text, handles)
    assert result["report_id"], json.dumps({k:result.get(k) for k in ["issues","products","comparison"]})
    assert result["status"] == "PARTIAL"  # Transport intentionally supplies no price evidence.
    assert len(result["products"]) == (3 if auto else 2)
    assert result["budget"]["used"]["understanding"] == 1
    assert result["budget"]["used"]["extraction"] > 0
    assert result["budget"]["used"]["searches"] <= 18
    with persistence.transaction() as tx:
        report = persistence.reports.get(tx, result["report_id"])
        content = json.loads(report["summary_json"])["content_json"]
        assert content["matrix"]["facts"]
        for product in result["products"]:
            if product["product_id"]:
                assert not persistence.fact_versions.list_current(tx, product["product_id"])
                assert not persistence.changes.list_for_run(tx, product["run_id"])
    assert any(call[0] == "get" for call in transport.calls)


@pytest.mark.parametrize("mode", ["clarify", "model_failure", "budget"])
def test_clarification_failures_and_budget_do_not_fake_success(persistence, mode):
    ctx, _ = context(mode=mode, limits=BudgetLimits(tokens=1) if mode == "budget" else None)
    flow = AgentRunner.workflow(persistence, ctx)
    text = "Compare Atlas and Birch"
    result = flow.execute(text, flow.prepare(text))
    assert not result["analysis_complete"]
    assert result["status"] != "COMPLETE"
    if mode in {"clarify", "budget"}:
        assert result["report_id"] is None


def test_formal_api_paid_gate_start_poll_read_export(persistence, monkeypatch):
    monkeypatch.delenv("WORKFLOW_PAID_ENABLED", raising=False)
    app = create_app(settings=settings(), persistence=persistence)
    ctx, _ = context()
    app.state.workflow_context_factory = lambda: ctx
    with TestClient(app) as client:
        assert client.post('/api/analyst/workflows', json={"text": "Compare Atlas and Birch", "allow_paid": True}).status_code == 403
        monkeypatch.setenv("WORKFLOW_PAID_ENABLED", "1")
        for name in ["RESEARCH_SEARCH_COST_MICROUSD", "RESEARCH_INPUT_COST_MICROUSD_PER_MILLION", "RESEARCH_OUTPUT_COST_MICROUSD_PER_MILLION"]:
            monkeypatch.setenv(name, "1000")
        assert client.get('/api/analyst/workflows/readiness').json()["data"]["ready"]
        # Replay the exact request captured from the shipped chat JS, not a
        # TestClient json= shortcut that silently supplies the missing header.
        wire = json.loads(subprocess.run(['node', 'tests/chat_workflow_submission.cjs', 'success', 'Compare Atlas and Birch'],
                         capture_output=True, text=True, encoding='utf-8', check=True).stdout)
        post = next(row for row in wire['requests'] if row['method'] == 'POST')
        accepted = client.post(post['url'], content=post['body'].encode(),
                               headers={'Content-Type': post['contentType']})
        assert accepted.status_code == 202, accepted.text
        rid = accepted.json()["data"]["run_id"]
        for _ in range(200):
            result = client.get(f'/api/analyst/workflows/{rid}').json()["data"]
            if result["status"] != "RUNNING": break
            time.sleep(.02)
        assert result["report_id"], json.dumps({k:result.get(k) for k in ["issues","products","comparison"]})
        report = client.get(f'/api/reports/{result["report_id"]}').json()["data"]
        assert client.get(f'/api/reports/{result["report_id"]}/download').text == report["content_markdown"]
        assert 'chat-mode' in client.get('/').text


@pytest.mark.parametrize("mode", ["complete", "two_rivals"])
def test_fully_evidenced_explicit_scope_can_complete_without_history(persistence, mode):
    ctx, _ = context(mode=mode)
    flow = AgentRunner.workflow(persistence, ctx)
    text = "Compare Atlas and Birch and Cedar core features"
    result = flow.execute(text, flow.prepare(text))
    assert result["status"] == "COMPLETE", result
    assert result["analysis_complete"] and result["report_id"]
    assert len(result["products"]) == (3 if mode == "two_rivals" else 2)
    assert result["budget"]["used"]["searches"] == (9 if mode == "two_rivals" else 6)
    assert result["budget"]["used"]["evaluation"] == 0


def test_schema_gate_stops_before_external_calls(persistence, monkeypatch):
    ctx, transport = context()
    def missing(*args): raise ValueError("COMPETITIVE_REPORT_SCHEMA_REQUIRED")
    monkeypatch.setattr(persistence.reports, "require_competitive_schema", missing)
    with pytest.raises(ValueError, match="SCHEMA_REQUIRED"):
        AgentRunner.workflow(persistence, ctx).prepare("Compare Atlas and Birch")
    assert not transport.calls and ctx.budget.used["models"] == 0


def test_budget_exhausted_after_first_fact_keeps_persisted_partial_report(persistence):
    ctx, _ = context(limits=BudgetLimits(extraction=1))
    flow = AgentRunner.workflow(persistence, ctx)
    text = "Compare Atlas and Birch"
    result = flow.execute(text, flow.prepare(text))
    assert result["status"] == "PARTIAL" and result["report_id"]
    assert result["budget"]["used"]["extraction"] == 1
    assert result["budget"]["exhausted"] == "extraction"
    with persistence.transaction() as tx:
        report = persistence.reports.get(tx, result["report_id"])
        content = json.loads(report["summary_json"])["content_json"]
    assert content["matrix"]["facts"] and not content["conclusions"]

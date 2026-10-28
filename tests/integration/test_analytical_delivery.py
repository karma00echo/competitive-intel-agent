"""Formal API, real repositories, production renderer; no external provider."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
from uuid import uuid4
from types import SimpleNamespace
import pytest
import requests
from fastapi.testclient import TestClient

from tests.integration.test_competitive_reports import seed, task
from tests.unit.test_competitive_matrix import synthesis_context
from tests.analytical_support import fixture_payload, reviewed
from tests.discovery_support import settings
from competitive_intel.services.agent_runner import AgentRunner
from competitive_intel.services.competitive_matrix_service import CompetitiveMatrixService
from competitive_intel.services.competitive_analysis_service import CompetitiveAnalysisService
from competitive_intel.domain.analytical_writing import writing_packet
from competitive_intel.web.app import create_app

pytestmark = pytest.mark.integration


def test_saved_chat_route_persists_reopens_exports_and_preserves_history(persistence, monkeypatch, tmp_path):
    monkeypatch.setattr(requests.Session, "request", lambda *a, **k: pytest.fail("Live network forbidden"))
    products = [seed(persistence, n) for n in ["Alpha", "Beta", "Gamma"]]
    plan = task().model_copy(update={"output_language":"zh-CN", "dimensions":["core_features", "pricing"]})
    original_context, _ = synthesis_context()
    original = AgentRunner.compare_products(persistence, plan, products, original_context)
    with persistence.transaction() as tx:
        before = persistence.reports.get(tx, original["report_id"])
    goal = "比较 Alpha、Beta 和 Gamma 的已有证据，提出策略验证建议。"
    calls = []
    def factory():
        ctx, _ = synthesis_context()
        ctx.report_writer = SimpleNamespace(origin="fixture", write=lambda packet: calls.append(packet) or fixture_payload(packet))
        matrix = CompetitiveMatrixService(persistence).build(plan, products)
        analysis = CompetitiveAnalysisService().analyze(matrix, ctx)
        packet = writing_packet(plan, analysis, goal)
        ctx.writing_reviews = reviewed(fixture_payload(packet), packet)
        return ctx
    app = create_app(settings=settings(), persistence=persistence)
    app.state.saved_writer_context_factory = factory
    with TestClient(app) as client:
        assert "已有证据 → AI 分析报告" in client.get('/').text
        payload = dict(report_id=original["report_id"], text=goal, request_id=str(uuid4()))
        result = client.post('/api/analyst/saved-writing', json=payload)
        assert result.status_code == 200, result.text
        data = result.json()["data"]
        assert data["delivery_status"] == "DEMO_READY" and data["status"] == "PARTIAL", data
        assert data["ai_status"] == "FIXTURE_VALIDATED"
        again = client.post('/api/analyst/saved-writing', json=payload).json()["data"]
        assert again == data and len(calls) == 1
        report = client.get(f'/api/reports/{data["report_id"]}').json()["data"]
        assert client.get(f'/reports/{data["report_id"]}').status_code == 200
        assert client.get(f'/api/reports/{data["report_id"]}/download').text == report["content_markdown"]
        assert "策略建议" in report["content_markdown"] and "Fixture" in report["content_markdown"]
        assert client.get(f'/api/reports/{data["report_id"]}').json()["data"] == report
        subprocess.run(['node','tests/fixtures/report_reading_dom.cjs','src/competitive_intel/web/static/app.js'],
            input=json.dumps(report), text=True, capture_output=True, check=True)
        assert client.post('/api/analyst/saved-writing',json={**payload,"text":"其他产品"}).status_code == 422
        assert client.post('/api/analyst/saved-writing',json={**payload,"text":goal+"新增问题"}).status_code == 409
        assert report['content_json']['source_report_id'] == original['report_id']
        # Review publication uses the stored candidate, not another model attempt.
        manifest=tmp_path/'reviews.json'
        manifest.write_text(json.dumps(factory().writing_reviews),encoding='utf-8')
        monkeypatch.setenv('REPORT_WRITER_REVIEWS',str(manifest))
        del app.state.saved_writer_context_factory
        published=client.post('/api/analyst/saved-writing',json={**payload,
            'request_id':str(uuid4()),'report_id':data['report_id']}).json()['data']
        assert published['delivery_status']=='DEMO_READY' and len(calls)==1
        new=client.get(f'/api/reports/{published["report_id"]}').json()['data']
        assert new['content_json']['source_report_id']==data['report_id']
        assert new['content_json']['presentation']['writing']['analytical']['candidate']==report['content_json']['presentation']['writing']['analytical']['candidate']
        assert all(v==0 for v in published['budget']['used'].values())
    with persistence.transaction() as tx:
        assert persistence.reports.get(tx, original["report_id"]) == before
    assert not data["budget"]["used"]["searches"] and not data["budget"]["used"]["fetches"]

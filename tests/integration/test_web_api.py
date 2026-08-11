from __future__ import annotations

import json
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from threading import Event

import pytest
from fastapi.testclient import TestClient

from competitive_intel.api.schemas import AnalysisRequest
from competitive_intel.config import DatabaseSettings, Settings
from competitive_intel.web import create_app
from competitive_intel.web.runtime import (
    AnalysisAlreadyRunning,
    AnalysisCapacityReached,
    AnalysisTaskManager,
)


def _settings() -> Settings:
    return Settings(
        database=DatabaseSettings(
            host="127.0.0.1", port=3306, name="unused_test",
            user="test", password="",
        )
    )


def _wait(client: TestClient, run_id: int) -> dict:
    for _ in range(100):
        data = client.get(f"/api/runs/{run_id}").json()["data"]
        if data["final_state"] in {
            "COMPLETED", "COMPLETED_WITH_WARNINGS", "FAILED"
        }:
            return data
        time.sleep(0.05)
    pytest.fail("fixture analysis did not reach a terminal state")


def test_app_factory_health_pages_and_static_assets(persistence) -> None:
    app = create_app(settings=_settings(), persistence=persistence)
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["database_status"] == "available"
        assert health.json()["fixture_available"] is True
        for path in (
            "/", "/workspace", "/dashboard", "/runs/1",
            "/competitors/1", "/reports/1",
        ):
            response = client.get(path)
            assert response.status_code == 200
            assert "text/html" in response.headers["content-type"]
            assert "<script>alert" not in response.text
        workspace = client.get("/")
        assert "竞品情报 Agent 工作台" in workspace.text
        assert "当前仅支持分析、刷新、报告、变化和运行查询" in workspace.text
        assert "真实事实提取：未接入" in workspace.text
        assert client.get("/static/app.css").status_code == 200
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/workspace.css").status_code == 200


def test_health_is_structured_when_database_is_unavailable() -> None:
    class BrokenDashboard:
        def ping(self, session):
            raise RuntimeError("database offline")

    class BrokenPersistence:
        dashboard = BrokenDashboard()

        @contextmanager
        def transaction(self):
            yield object()

    app = create_app(
        settings=_settings(),
        persistence=BrokenPersistence(),
        task_manager=AcceptingManager(),
    )
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["database_status"] == "unavailable"


def test_fixture_analysis_all_read_apis_and_price_change(persistence) -> None:
    app = create_app(settings=_settings(), persistence=persistence)
    with TestClient(app) as client:
        accepted = client.post("/api/analyses", json={
            "competitor_name": "Notion", "search_provider": "fixture",
            "fact_provider": "fixture", "agent_provider": "fixture",
            "fixture_scenario": "default", "max_tool_calls": 20,
        })
        assert accepted.status_code == 202
        run_id = accepted.json()["run_id"]
        completed = _wait(client, run_id)
        assert completed["final_state"] == "COMPLETED"
        while app.state.task_manager.active_count:
            time.sleep(0.01)

        competitor_list = client.get("/api/competitors").json()["data"]["items"]
        assert len(competitor_list) == 1
        competitor_id = competitor_list[0]["competitor_id"]
        assert client.get(f"/api/competitors/{competitor_id}").status_code == 200
        sources = client.get(
            f"/api/competitors/{competitor_id}/sources"
        ).json()["data"]["items"]
        assert len(sources) == 4
        assert all("raw_content" not in item for item in sources)
        facts = client.get(
            f"/api/competitors/{competitor_id}/facts"
        ).json()["data"]["items"]
        assert facts and all(item["display_value"] for item in facts)
        assert client.get(
            f"/api/competitors/{competitor_id}/facts?category=PRICE"
        ).status_code == 200
        assert client.get(f"/api/runs/{run_id}/events").json()["data"]["items"]
        assert client.get(f"/api/runs/{run_id}/tool-calls").json()["data"]["items"]
        reports = client.get(
            f"/api/competitors/{competitor_id}/reports"
        ).json()["data"]["items"]
        report_id = reports[0]["report_id"]
        report = client.get(f"/api/reports/{report_id}")
        assert report.status_code == 200
        download = client.get(
            f"/api/reports/{report_id}/download?format=markdown"
        )
        assert download.status_code == 200
        assert download.headers["content-type"].startswith("text/markdown")
        assert ".." not in download.headers["content-disposition"]

        refresh = client.post("/api/analyses", json={
            "competitor_name": "Notion", "fixture_scenario": "price_changed",
            "search_provider": "fixture", "fact_provider": "fixture",
            "agent_provider": "fixture", "max_tool_calls": 20,
        })
        assert refresh.status_code == 202
        refresh_result = _wait(client, refresh.json()["run_id"])
        assert refresh_result["final_state"] == "COMPLETED"
        assert refresh_result["change_summary"]["modified_count"] == 1
        replay = client.get(
            f"/api/workspace/runs/{refresh_result['run_id']}"
        )
        assert replay.status_code == 200
        workspace = replay.json()["data"]
        assert workspace["run"]["progress_percent"] == 100
        assert workspace["run"]["run_mode"] == "REFRESH"
        assert workspace["run"]["page_comparison_summary"] == {
            "UNCHANGED": 3, "PAGE_CHANGED": 1,
        }
        assert workspace["competitor"]["canonical_name"] == "Notion"
        assert workspace["events"]
        assert workspace["tool_calls"]
        assert all(call["display_name"] for call in workspace["tool_calls"])
        assert workspace["sources"]
        assert workspace["facts"]
        modified_change = next(
            item for item in workspace["changes"]
            if item["change_type"] == "MODIFIED"
        )
        assert "10" in modified_change["old_display_value"]
        assert "12" in modified_change["new_display_value"]
        assert workspace["report"]["download_url"].endswith("format=markdown")
        message_types = {message["type"] for message in workspace["messages"]}
        assert {
            "USER_REQUEST", "AGENT_PLAN", "MODE_SELECTED",
            "CHANGE_RESULT", "REPORT_RESULT", "FINAL_SUMMARY",
        } <= message_types
        replay_text = replay.text
        assert "api_key" not in replay_text
        assert "raw_html" not in replay_text
        assert "clean_content" not in replay_text
        changes = client.get(
            f"/api/competitors/{competitor_id}/changes?change_type=MODIFIED"
        ).json()["data"]["items"]
        assert len(changes) == 1
        assert "10" in changes[0]["old_display_value"]
        assert "12" in changes[0]["new_display_value"]
        refresh_report = client.get(
            f"/api/reports/{refresh_result['report_id']}"
        ).json()["data"]
        modified = next(
            section for section in refresh_report["content_json"]["sections"]
            if section["heading"] == "Modified facts"
        )
        assert isinstance(modified["items"][0]["old_value"], dict)
        assert client.get(
            f"/api/runs?competitor_id={competitor_id}"
        ).json()["data"]["items"]


def test_workspace_historical_replay_does_not_start_analysis(persistence) -> None:
    with persistence.transaction() as session:
        run_id = persistence.agent_runs.create(
            session, input_name="Replay", normalized_input="replay"
        )
        persistence.agent_runs.finish(
            session, run_id, status="FAILED", current_state="FAILED",
            error_code="FIXTURE_FAILURE", error_message="<script>alert(1)</script>",
        )
        before = len(
            persistence.dashboard.list_runs(
                session, competitor_id=None, state=None, limit=100, offset=0
            )
        )
    app = create_app(settings=_settings(), persistence=persistence)
    with TestClient(app) as client:
        response = client.get(f"/api/workspace/runs/{run_id}")
        workspace_html = client.get("/").text
    assert response.status_code == 200
    assert response.json()["data"]["messages"][-1]["type"] == "FINAL_SUMMARY"
    assert "<script>alert(1)</script>" not in workspace_html
    assert "textContent" in client.get("/static/app.js").text
    with persistence.transaction() as session:
        after = len(
            persistence.dashboard.list_runs(
                session, competitor_id=None, state=None, limit=100, offset=0
            )
        )
    assert after == before


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"competitor_name": ""}, "INVALID_REQUEST"),
        ({"competitor_name": "A", "search_provider": "unknown"}, "INVALID_REQUEST"),
        ({"competitor_name": "A", "fixture_scenario": "unknown"}, "INVALID_REQUEST"),
        ({"competitor_name": "A", "max_tool_calls": 1000}, "INVALID_REQUEST"),
        (
            {"competitor_name": "Linear", "search_provider": "serper",
             "skip_fact_extraction": False},
            "REAL_CONTENT_FIXTURE_FACTS_FORBIDDEN",
        ),
    ],
)
def test_analysis_validation_is_structured(persistence, payload, code) -> None:
    app = create_app(settings=_settings(), persistence=persistence)
    with TestClient(app) as client:
        response = client.post("/api/analyses", json=payload)
    assert response.status_code == 422
    assert response.json()["ok"] is False
    assert response.json()["error_code"] == code


class AcceptingManager:
    active_count = 0

    def start(self, payload) -> int:
        assert payload.search_provider == "serper"
        assert payload.skip_fact_extraction is True
        return 77

    def shutdown(self) -> None:
        pass


def test_serper_skip_request_is_accepted_without_network(persistence) -> None:
    app = create_app(
        settings=_settings(), persistence=persistence,
        task_manager=AcceptingManager(),
    )
    with TestClient(app) as client:
        response = client.post("/api/analyses", json={
            "competitor_name": "Linear", "search_provider": "serper",
            "skip_fact_extraction": True,
        })
    assert response.status_code == 202
    assert response.json()["run_id"] == 77


def test_tool_call_api_removes_secrets_and_large_page_content(persistence) -> None:
    with persistence.transaction() as session:
        run_id = persistence.agent_runs.create(
            session, input_name="Acme", normalized_input="acme"
        )
        call_id = persistence.tool_calls.create(
            session, run_id=run_id, stage_event_id=None, call_index=1,
            tool_name="safe_tool",
            input_summary={"api_key": "secret-value", "name": "Acme"},
        )
        persistence.tool_calls.finish(
            session, call_id, status="SUCCEEDED",
            output_summary={
                "clean_content": "private page body",
                "summary": "x" * 5000,
            },
        )
    app = create_app(settings=_settings(), persistence=persistence)
    with TestClient(app) as client:
        text = client.get(f"/api/runs/{run_id}/tool-calls").text
    assert "secret-value" not in text
    assert "private page body" not in text
    assert len(text) < 3000


class BlockingRunner:
    def __init__(self, sink, release: Event, run_id: int):
        self._sink, self._release, self._run_id = sink, release, run_id

    def run(self, *args, **kwargs):
        self._sink({"event": "run_started", "run_id": self._run_id})
        self._release.wait(timeout=2)


def test_task_manager_same_competitor_and_global_capacity(persistence) -> None:
    release = Event()
    counter = iter((101, 102, 103))
    manager = AnalysisTaskManager(
        persistence,
        lambda request, sink: BlockingRunner(sink, release, next(counter)),
        max_workers=2,
    )
    try:
        request = AnalysisRequest(competitor_name="Acme")
        assert manager.start(request) == 101
        with pytest.raises(AnalysisAlreadyRunning):
            manager.start(request)
        assert manager.start(AnalysisRequest(competitor_name="Other")) == 102
        with pytest.raises(AnalysisCapacityReached):
            manager.start(AnalysisRequest(competitor_name="Third"))
    finally:
        release.set()
        manager.shutdown()


def test_background_exception_marks_started_run_failed(persistence) -> None:
    class FailingRunner:
        def __init__(self, sink):
            self.sink = sink

        def run(self, competitor_name, **kwargs):
            with persistence.transaction() as session:
                run_id = persistence.agent_runs.create(
                    session, input_name=competitor_name,
                    normalized_input=competitor_name.casefold(),
                )
            self.sink({"event": "run_started", "run_id": run_id})
            raise RuntimeError("controlled fixture failure")

    manager = AnalysisTaskManager(
        persistence, lambda request, sink: FailingRunner(sink), max_workers=1
    )
    run_id = manager.start(AnalysisRequest(competitor_name="Failure"))
    for _ in range(100):
        with persistence.transaction() as session:
            run = persistence.agent_runs.get(session, run_id)
        if run["status"] == "FAILED":
            break
        time.sleep(0.01)
    manager.shutdown()
    assert run["status"] == "FAILED"
    assert run["error_code"] == "BACKGROUND_TASK_EXCEPTION"

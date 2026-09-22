from fastapi.testclient import TestClient

from competitive_intel.web import create_app
from test_web_api import _settings, _wait


def test_command_center_empty_and_navigation(persistence):
    with TestClient(create_app(settings=_settings(), persistence=persistence)) as client:
        data=client.get("/api/command-center").json()["data"]
        assert data["metrics"]["competitor_count"] == 0
        assert data["recent_signals"] == [] and data["attention"] == []
        for route in ["/", "/signals", "/analyst", "/competitors", "/reports", "/developer", "/workspace", "/developer/runs/1"]:
            page=client.get(route)
            assert page.status_code == 200
            for label in ["Command Center", "Signals", "Analyst", "Competitors", "Reports", "Developer"]:
                assert label in page.text
        home=client.get("/").text
        assert "chat-input" in home and "stage_events" not in home
        assert "竞品情报 Agent 工作台" in client.get("/workspace").text
        assert "textContent" in client.get("/static/intelligence.js").text
        assert "innerHTML" not in client.get("/static/intelligence.js").text
        assert "No verified facts available yet." in client.get("/static/intelligence.js").text
        assert client.get("/api/analyst/command", params={"text":"随便聊聊"}).json()["data"]["action"]=="unsupported"


def test_warning_attention_and_real_empty_facts(persistence):
    with persistence.transaction() as session:
        cid=persistence.competitors.create(session,canonical_name="Real product",normalized_name="real product")
        rid=persistence.agent_runs.create(session,input_name="Real product",normalized_input="real product")
        persistence.agent_runs.update_context(session,rid,competitor_id=cid,run_mode="BASELINE")
        persistence.agent_runs.finish(session,rid,status="COMPLETED",current_state="COMPLETED")
        call=persistence.tool_calls.create(session,run_id=rid,stage_event_id=None,call_index=1,tool_name="finalize_run_summary",input_summary={})
        persistence.tool_calls.finish(session,call,status="SUCCEEDED",output_summary={"final_state":"COMPLETED_WITH_WARNINGS","api_key":"SECRET_MUST_NOT_LEAK"})
    with TestClient(create_app(settings=_settings(),persistence=persistence)) as client:
        response=client.get("/api/command-center")
        data=response.json()["data"]
        assert data["metrics"]["competitor_count"] == 1
        assert data["metrics"]["attention_count"] == 1
        assert "Latest analysis completed with warnings" in data["attention"][0]["warnings"]
        assert "SECRET_MUST_NOT_LEAK" not in response.text
        profile=client.get(f"/api/competitors/{cid}/intelligence").json()["data"]
        assert profile["facts"] == [] and profile["reports"] == []
        assert client.get("/api/competitors/999999/intelligence").status_code==404


def test_later_registered_run_supersedes_unlinked_failure(persistence):
    with persistence.transaction() as session:
        old=persistence.agent_runs.create(session,input_name="Recovered",normalized_input="recovered")
        persistence.agent_runs.finish(session,old,status="FAILED",current_state="FAILED")
        cid=persistence.competitors.create(session,canonical_name="Recovered",normalized_name="recovered")
        new=persistence.agent_runs.create(session,input_name="Recovered",normalized_input="recovered",competitor_id=cid)
        persistence.agent_runs.finish(session,new,status="COMPLETED",current_state="COMPLETED")
    with TestClient(create_app(settings=_settings(),persistence=persistence)) as client:
        data=client.get("/api/command-center").json()["data"]
        assert len(data["attention"])==1
        assert data["attention"][0]["run_id"]==new
        assert "Latest analysis failed" not in data["attention"][0]["warnings"]


def test_signals_filter_order_pagination_and_status(persistence):
    with persistence.transaction() as session:
        cid=persistence.competitors.create(session,canonical_name="<script>alert(1)</script>",normalized_name="acme")
        rid=persistence.agent_runs.create(session,input_name="Acme",normalized_input="acme")
        for kind in ["ADDED","MODIFIED","REMOVED","UNKNOWN","UNCHANGED"]:
            persistence.changes.create(session,competitor_id=cid,run_id=rid,change_type=kind,
                fact_key="price.plus",old_value={"amount":10},new_value={"amount":12},
                evidence_text="evidence "*100,verification_status="CONFIRMED")
    with TestClient(create_app(settings=_settings(),persistence=persistence)) as client:
        data=client.get("/api/signals").json()["data"]
        assert [x["change_type"] for x in data["items"]]==["UNCOMPARABLE","REMOVED","MODIFIED","ADDED"]
        assert all(len(x["evidence_excerpt"])==500 for x in data["items"])
        assert client.get("/api/command-center").json()["data"]["metrics"]["signals_30d"]==4
        for kind in ["ADDED","MODIFIED","REMOVED","UNCOMPARABLE"]:
            items=client.get("/api/signals",params={"change_type":kind,"category":"Pricing","competitor_id":cid}).json()["data"]["items"]
            assert len(items)==1 and items[0]["change_type"]==kind
        assert len(client.get("/api/signals?status=needs_review").json()["data"]["items"])==1
        assert len(client.get("/api/signals?status=confirmed").json()["data"]["items"])==3
        assert client.get("/api/signals?category=Feature").json()["data"]["items"]==[]
        assert client.get("/api/signals?start=2099-01-01").json()["data"]["items"]==[]
        first=client.get("/api/signals?limit=2").json()["data"]
        second=client.get("/api/signals?limit=2&offset=2").json()["data"]
        assert first["has_more"] and not second["has_more"]
        assert len(client.get("/api/signals?history=true").json()["data"]["items"])==5
        assert "<script>alert(1)</script>" not in client.get(f"/competitors/{cid}").text
        for query in ["limit=101","offset=-1","category=unknown","start=2026-03-01&end=2026-01-01"]:
            assert client.get(f"/api/signals?{query}").status_code==422


def test_product_profile_pricing_features_sources_reports(persistence):
    with TestClient(create_app(settings=_settings(),persistence=persistence)) as client:
        for scenario in ["default","price_changed"]:
            accepted=client.post("/api/analyses",json={"competitor_name":"Notion","fixture_scenario":scenario,"max_tool_calls":20})
            result=_wait(client,accepted.json()["run_id"])
            assert result["final_state"]=="COMPLETED"
        cid=result["competitor_id"]
        data=client.get(f"/api/competitors/{cid}/intelligence").json()["data"]
        assert {"PRICE","FEATURE"} <= {x["category"] for x in data["facts"]}
        assert all(x["evidence_excerpt"] and x["source_url"] for x in data["facts"])
        assert len(data["sources"])==4 and len(data["reports"])==2
        for category, expected in [("Pricing", {"PRICE", "PLAN"}), ("Feature", {"FEATURE"})]:
            facts=client.get(f"/api/competitors/{cid}/intelligence?fact_category={category}&limit=1").json()["data"]["facts"]
            assert len(facts)==1 and facts[0]["category"] in expected
        signals=client.get("/api/signals?change_type=MODIFIED").json()["data"]["items"]
        assert len(signals)==1 and "12" in signals[0]["new_value"]
        assert signals[0]["source_url"] and signals[0]["evidence_excerpt"]
        assert client.get("/api/reports?limit=1").json()["data"]["has_more"]
        assert client.get(f"/api/workspace/runs/{result['run_id']}").json()["data"]["tool_calls"]
        text=client.get("/api/command-center").text
        assert "raw_html" not in text and "password" not in text and "api_key" not in text

"""Disposable MySQL, injected HTTP only. These are not real E2E acceptance tests."""

from dataclasses import replace
from datetime import datetime
from hashlib import sha256
import json

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from tests.discovery_support import spec, settings
from tests.unit.test_competitive_matrix import row, synthesis_context
from competitive_intel.domain.competitive_matrix import ResearchProduct
from competitive_intel.domain.fact_comparison import FactNormalizer
from competitive_intel.persistence.schema import initialize_schema
from competitive_intel.services.agent_runner import AgentRunner
from competitive_intel.services.report_service import CompetitorReportService
from competitive_intel.web.app import create_app

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("Live HTTP forbidden"))


def seed(persistence, name, *, failed=False):
    data = row()
    when = datetime(2026, 1, 1)
    with persistence.transaction() as tx:
        cid = persistence.competitors.create(tx, canonical_name=name, normalized_name=name.casefold())
        rid = persistence.agent_runs.create(tx, input_name=name, normalized_input=name.casefold(), competitor_id=cid)
        url = f"https://{name.lower()}.example/"
        sid = persistence.sources.create(tx, competitor_id=cid, source_type="HOMEPAGE", url=url,
            normalized_url=url, domain=f"{name.lower()}.example", verification_status="VERIFIED", confidence=0.9)
        snap = persistence.snapshots.create(tx, source_id=sid, run_id=rid, requested_url=url, final_url=url,
            fetch_status="SUCCESS", fetched_at=when, clean_content=data["clean_content"], clean_hash=data["clean_hash"])
        fid = persistence.product_facts.create(tx, competitor_id=cid, run_id=rid, snapshot_id=snap,
            fact_category="FEATURE", fact_key=data["fact_key"], fact_value=data["fact_value"], statement_type="FACT",
            source_url=url, evidence_text=data["observed_evidence"], confidence=0.9, extracted_at=when, evidence_status="CONFIRMED")
        canonical = FactNormalizer().canonical_json("FEATURE", data["fact_value"])
        persistence.fact_versions.create(tx, fact_id=fid, competitor_id=cid, source_id=sid,
            normalized_value=data["normalized_value"], normalized_value_hash=sha256(canonical.encode()).hexdigest(), valid_from=when)
        persistence.fact_observations.create_idempotent(tx, competitor_id=cid, run_id=rid, fact_id=fid,
            source_id=sid, snapshot_id=snap, evidence_text=data["observed_evidence"], confidence=0.9, observed_at=when)
        persistence.agent_runs.finish(tx, rid, status="FAILED" if failed else "COMPLETED", current_state="FAILED" if failed else "COMPLETED")
    return ResearchProduct(name, cid, rid, True)


def task():
    return spec(target="Alpha", competitors=["Beta", "Gamma"], discover_competitors=False, dimensions=["core_features"])


def test_three_product_report_is_idempotent_and_api_export_matches_storage(persistence):
    products = [seed(persistence, name) for name in ["Alpha", "Beta", "Gamma"]]
    context, transport = synthesis_context()
    context.budget.reserve(searches=5, fetches=6, models=3, extraction=3, tokens=100)
    result = AgentRunner.compare_products(persistence, task(), products, context)
    assert result["status"] == "COMPLETE", result
    assert result["report_type"] == "COMPETITIVE_ANALYSIS"
    assert AgentRunner.compare_products(persistence, task(), products, context) == result
    assert transport.calls == 1 and result["budget"]["used"]["searches"] == 5
    report = CompetitorReportService(persistence).get(run_id=result["run_id"])
    assert len(report.content_json["matrix"]["products"]) == 3
    with TestClient(create_app(settings=settings(), persistence=persistence)) as client:
        body = client.get(f"/api/reports/{report.report_id}").json()["data"]
        exported = client.get(f"/api/reports/{report.report_id}/download")
        assert body["content_json"] == report.content_json
        assert body["content_markdown"] == exported.text == report.content_markdown
        run_body = client.get(f"/api/runs/{result['run_id']}").json()["data"]
        assert run_body["execution_phase"] == "competitive_analysis" and run_body["analysis_complete"]
    with persistence.transaction() as tx:
        assert not persistence.changes.list_for_run(tx, result["run_id"])
        assert persistence.agent_runs.get(tx, result["run_id"])["run_mode"] == "UNKNOWN"
        for product in products:
            assert not persistence.fact_versions.list_current(tx, product.product_id)
            assert all(o["comparison_status"] == "PENDING" for o in persistence.fact_observations.list_for_run(tx, product.run_id))
        assert persistence.reports.get_latest_for_competitor(tx, products[0].product_id) is None
    with pytest.raises(ValueError, match="TASK_SCOPE_CHANGED"):
        AgentRunner.compare_products(persistence, task().model_copy(update={"dimensions": ["pricing"]}), products, context)


@pytest.mark.parametrize("case", ["missing", "failed_product", "budget", "provider", "unsupported"])
def test_partial_reports_never_become_complete(persistence, case):
    products = [seed(persistence, name, failed=case == "failed_product" and name == "Beta") for name in ["Alpha", "Beta", "Gamma"]]
    context, _ = synthesis_context("http_error" if case == "provider" else "unsupported" if case == "unsupported" else "ok")
    plan = task().model_copy(update={"dimensions": ["core_features", "pricing"]}) if case == "missing" else task()
    if case == "budget":
        context.budget.reserve(synthesis=1)
    result = AgentRunner.compare_products(persistence, plan, products, context)
    assert result["status"] == "PARTIAL", result
    assert result["report_type"] == "COMPETITIVE_ANALYSIS_PARTIAL" and not result["analysis_complete"]
    report = CompetitorReportService(persistence).get(report_id=result["report_id"])
    assert report.content_json["matrix"]["facts"]
    if case in {"budget", "provider", "unsupported"}:
        assert not report.content_json["conclusions"]


def test_publication_failure_rolls_back_report_and_records_failed_run(persistence, monkeypatch):
    products = [seed(persistence, name) for name in ["Alpha", "Beta", "Gamma"]]
    context, transport = synthesis_context()
    original = persistence.reports.create
    def fail_after_insert(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic transaction failure")
    monkeypatch.setattr(persistence.reports, "create", fail_after_insert)
    result = AgentRunner.compare_products(persistence, task(), products, context)
    assert result["status"] == "FAILED" and result["report_id"] is None
    assert CompetitorReportService(persistence).get(run_id=result["run_id"]) is None
    assert AgentRunner.compare_products(persistence, task(), products, context) == result
    assert transport.calls == 1


def test_004_preserves_003_history_and_can_reenter_after_missing_marker(persistence, mysql_engine):
    product = seed(persistence, "Alpha")
    with persistence.transaction() as tx:
        old_id = persistence.reports.create(tx, competitor_id=product.product_id, run_id=product.run_id,
            report_type="BASELINE", status="GENERATED", generator_version="test", content_markdown="historical report")
        old = persistence.reports.get(tx, old_id)
        observations = persistence.fact_observations.list_for_run(tx, product.run_id)
    fks = inspect(mysql_engine).get_foreign_keys("reports")
    def history():
        with mysql_engine.connect() as connection:
            return {table: sorted(json.dumps(dict(r._mapping), sort_keys=True, default=str)
                                  for r in connection.exec_driver_sql(f"SELECT * FROM `{table}`"))
                    for table in inspect(mysql_engine).get_table_names() if table != "schema_migrations"}
    before = history()
    try:
        with mysql_engine.begin() as connection:
            assert connection.exec_driver_sql("SELECT DATABASE()").scalar() == "competitive_intel_test"
            connection.exec_driver_sql("ALTER TABLE reports MODIFY report_type ENUM('BASELINE','CHANGE_TRACKING','PARTIAL_EVIDENCE') NOT NULL")
            connection.exec_driver_sql("DELETE FROM schema_migrations WHERE version='004_competitive_reports.sql'")
        with persistence.transaction() as tx:
            with pytest.raises(ValueError, match="SCHEMA_REQUIRED"):
                persistence.reports.require_competitive_schema(tx)
        initialize_schema(mysql_engine)
        initialize_schema(mysql_engine)
        with mysql_engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM schema_migrations WHERE version='004_competitive_reports.sql'")
        initialize_schema(mysql_engine)
        with persistence.transaction() as tx:
            persistence.reports.require_competitive_schema(tx)
            assert persistence.reports.get(tx, old_id) == old
            assert persistence.fact_observations.list_for_run(tx, product.run_id) == observations
        assert inspect(mysql_engine).get_foreign_keys("reports") == fks
        assert history() == before
    finally:
        initialize_schema(mysql_engine)


def test_auto_discovery_handoff_preserves_selected_scope_and_budget(persistence):
    from tests.discovery_support import service
    discovery, _ = service()
    plan = spec(dimensions=["core_features"])
    found = AgentRunner.discover_competitors(persistence, plan, discovery)
    products = [seed(persistence, name) for name in [plan.target, *found["selected"]]]
    from competitive_intel.services.research_context import ResearchContext
    from tests.unit.test_competitive_matrix import SynthesisTransport
    transport = SynthesisTransport()
    context = ResearchContext.from_trusted_audit(settings(), found, allow_paid=True, session_factory=lambda _: transport)
    context.budget.reserve(extraction=3, models=3, fetches=3)
    result = AgentRunner.compare_products(persistence, plan, products, context)
    assert result["status"] == "COMPLETE", result
    assert result["budget"]["used"]["searches"] == found["budget"]["used"]["searches"]
    assert result["budget"]["used"]["models"] == found["budget"]["used"]["models"] + 4
    report = CompetitorReportService(persistence).get(report_id=result["report_id"])
    assert report.content_json["discovery_run_id"] == found["run_id"]
    assert [p["name"] for p in report.content_json["matrix"]["products"]] == [plan.target, *found["selected"]]


def test_concurrent_duplicate_returns_running_claim_without_double_call(persistence):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    products = [seed(persistence, name) for name in ["Alpha", "Beta", "Gamma"]]
    context, transport = synthesis_context()
    entered, release = Event(), Event()
    original = transport.post
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)
    transport.post = blocked
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(AgentRunner.compare_products, persistence, task(), products, context)
        try:
            assert entered.wait(10)
            repeated = AgentRunner.compare_products(persistence, task(), products, context)
            assert repeated["status"] == "RUNNING"
        finally:
            release.set()
        result = pending.result(timeout=10)
    assert repeated["run_id"] == result["run_id"] and transport.calls == 1


def test_persisted_extraction_conflict_excludes_surviving_fact(persistence):
    products = [seed(persistence, name) for name in ["Alpha", "Beta", "Gamma"]]
    with persistence.transaction() as tx:
        call = persistence.tool_calls.create(tx, run_id=products[0].run_id, stage_event_id=None,
            call_index=1, tool_name="extract_facts", input_summary={})
        persistence.tool_calls.finish(tx, call, status="SUCCEEDED", output_summary={"provider_calls": [
            {"identity_conflicts": [{"canonical_identity": "feature.docs"}]}]})
    context, _ = synthesis_context()
    result = AgentRunner.compare_products(persistence, task(), products, context)
    report = CompetitorReportService(persistence).get(report_id=result["report_id"])
    assert result["status"] == "PARTIAL"
    assert report.content_json["matrix"]["products"][0]["cells"]["core_features"]["status"] == "SOURCE_CONFLICT"

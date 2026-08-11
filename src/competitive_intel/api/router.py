"""JSON API backed exclusively by services and persistence repositories."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from competitive_intel.api.schemas import (
    APIEnvelope,
    AnalysisAccepted,
    AnalysisRequest,
    HealthResponse,
)
from competitive_intel.services import CompetitorReportService
from competitive_intel.web.display import FactDisplayFormatter, decode_json
from competitive_intel.web.runtime import (
    AnalysisAlreadyRunning,
    AnalysisCapacityReached,
    AnalysisStartFailed,
)
from competitive_intel.web.workspace import (
    STATE_LABELS,
    build_message_stream,
    progress_for_events,
    tool_view,
)


router = APIRouter(prefix="/api")
formatter = FactDisplayFormatter()
SENSITIVE_KEYS = {
    "api_key", "password", "authorization", "x-api-key", "raw_html",
    "raw_content", "clean_content", "environment", "env",
}


def _error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={"ok": False, "error_code": code, "error_message": message},
    )


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if depth > 8:
        return "[truncated]"
    if isinstance(value, str):
        decoded = decode_json(value)
        if decoded is not value:
            return _sanitize(decoded, depth=depth + 1)
        return value[:1000] + ("…" if len(value) > 1000 else "")
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item, depth=depth + 1)
            for key, item in list(value.items())[:50]
            if str(key).casefold() not in SENSITIVE_KEYS
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, depth=depth + 1) for item in value[:50]]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _run_summary_from_calls(calls: list[dict[str, Any]]) -> dict[str, Any]:
    for call in reversed(calls):
        if call["tool_name"] == "finalize_run_summary":
            payload = decode_json(call.get("output_summary"))
            if isinstance(payload, dict):
                return payload.get("summary", payload)
    return {}


def _page_comparison_summary(calls: list[dict[str, Any]]) -> dict[str, int]:
    for call in reversed(calls):
        if call["tool_name"] != "refresh_verified_sources":
            continue
        payload = decode_json(call.get("output_summary"))
        if not isinstance(payload, dict):
            return {}
        return dict(
            Counter(
                page.get("page_status")
                for page in payload.get("pages", [])[:100]
                if isinstance(page, dict) and page.get("page_status")
            )
        )
    return {}


def _run_view(run: dict[str, Any], calls: list[dict[str, Any]]) -> dict[str, Any]:
    summary = _run_summary_from_calls(calls)
    final_state = summary.get("final_state")
    if not final_state:
        final_state = "FAILED" if run["status"] == "FAILED" else (
            run["current_state"] if run["status"] == "RUNNING" else "COMPLETED"
        )
    warnings = summary.get("warnings", [])
    errors = summary.get("errors", [])
    report_summary = decode_json(run.get("report_summary")) or {}
    return {
        "run_id": int(run["id"]),
        "competitor": run.get("competitor_name") or run["input_name"],
        "competitor_id": run.get("competitor_id"),
        "run_mode": (
            "REFRESH" if run.get("run_mode") == "TRACKING" else run.get("run_mode")
        ),
        "final_state": final_state if run["status"] != "RUNNING" else None,
        "current_state": run["current_state"],
        "started_at": run["started_at"],
        "finished_at": run.get("finished_at"),
        "tool_call_count": int(run["tool_call_count"]),
        "warning_count": len(warnings),
        "error_count": len(errors) + (1 if run.get("error_message") else 0),
        "warnings": _sanitize(warnings),
        "errors": _sanitize(errors or ([run["error_message"]] if run.get("error_message") else [])),
        "report_id": run.get("report_id"),
        "change_summary": summary.get(
            "change_summary", report_summary.get("change_summary", {})
        ),
        "provider_summary": {
            "search_provider": summary.get("search_provider", "fixture"),
            "fetch_mode": summary.get("fetch_mode", "fixture"),
            "agent_provider": summary.get("agent_provider", "fixture"),
            "fact_provider": summary.get("fact_provider", "fixture"),
        },
        "fact_extraction_status": summary.get("fact_extraction_status"),
        "fact_extraction_reason": summary.get("fact_extraction_reason"),
        "page_fetch_success_count": summary.get("page_fetch_success_count", 0),
        "page_fetch_failure_count": summary.get("page_fetch_failure_count", 0),
        "verified_source_count": summary.get("verified_source_count", 0),
        "confirmed_fact_count": summary.get("confirmed_fact_count", 0),
    }


def _event_view(row: dict[str, Any]) -> dict[str, Any]:
    details = decode_json(row["details_json"]) or {}
    stage = details.get("logical_state", row["stage"])
    return {
        "event_id": row["id"],
        "stage": stage,
        "display_name": STATE_LABELS.get(stage, stage),
        "attempt": row["attempt_no"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "details": _sanitize(details),
        "error_code": row["error_code"],
        "error_message": _sanitize(row["error_message"]),
    }


def _tool_call_view(row: dict[str, Any]) -> dict[str, Any]:
    return tool_view(
        {
            "tool_call_id": row["id"],
            "call_index": row["call_index"],
            "tool_name": row["tool_name"],
            "status": row["status"],
            "input": _sanitize(row["input_summary"]),
            "output": _sanitize(row["output_summary"]),
            "retryable": bool(row["retryable"]),
            "duration_ms": row["duration_ms"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "error_code": row["error_code"],
            "error_message": _sanitize(row["error_message"]),
        }
    )


def _source_view(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_id": row["id"],
        "source_type": row["source_type"],
        "url": row["url"],
        "verification_status": row["verification_status"],
        "enabled": bool(row["is_active"]),
        "latest_snapshot_status": row["latest_snapshot_status"],
        "latest_fetched_at": row["latest_fetched_at"],
        "evidence_excerpt": (row.get("verification_reason") or "")[:500],
    }


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    database_status = "available"
    try:
        with request.app.state.persistence.transaction() as session:
            request.app.state.persistence.dashboard.ping(session)
    except Exception:
        database_status = "unavailable"
    return HealthResponse(
        status="ok" if database_status == "available" else "degraded",
        database_status=database_status,
        app_version=request.app.version,
        fixture_available=True,
        serper_configured=bool(request.app.state.settings.search.api_key),
        active_task_count=request.app.state.task_manager.active_count,
    )


@router.get("/competitors", response_model=APIEnvelope)
def competitors(
    request: Request,
    search: str | None = Query(default=None, max_length=120),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
    sort: str = Query(default="updated_desc"),
) -> APIEnvelope:
    if sort not in {"updated_desc", "name_asc", "name_desc"}:
        raise _error(422, "INVALID_SORT", "Unsupported competitor sort.")
    with request.app.state.persistence.transaction() as session:
        rows = request.app.state.persistence.dashboard.list_competitors(
            session, search=search, limit=limit, offset=offset, sort=sort
        )
    items = [
        {
            "competitor_id": row["id"],
            "name": row["canonical_name"],
            "normalized_name": row["normalized_name"],
            "official_homepage": row["official_homepage"],
            "verified_source_count": int(row["verified_source_count"]),
            "current_fact_count": int(row["current_fact_count"]),
            "latest_run_id": row["latest_run_id"],
            "latest_run_status": row["latest_run_status"],
            "latest_report_id": row["latest_report_id"],
            "updated_at": row["updated_at"],
        }
        for row in rows
    ]
    return APIEnvelope(data={"items": items, "limit": limit, "offset": offset})


def _require_competitor(request: Request, competitor_id: int) -> dict[str, Any]:
    with request.app.state.persistence.transaction() as session:
        row = request.app.state.persistence.dashboard.competitor_overview(
            session, competitor_id
        )
    if not row:
        raise _error(404, "COMPETITOR_NOT_FOUND", "Competitor was not found.")
    return row


@router.get("/competitors/{competitor_id}", response_model=APIEnvelope)
def competitor_detail(request: Request, competitor_id: int) -> APIEnvelope:
    row = _require_competitor(request, competitor_id)
    with request.app.state.persistence.transaction() as session:
        facts = request.app.state.persistence.fact_versions.list_current(
            session, competitor_id
        )
        changes = request.app.state.persistence.changes.list_for_competitor(
            session, competitor_id
        )
        latest_run = request.app.state.persistence.agent_runs.get_latest_for_competitor(
            session, competitor_id
        )
        latest_report = request.app.state.persistence.reports.get_latest_for_competitor(
            session, competitor_id
        )
    categories = Counter(item["fact_category"] for item in facts)
    recent_changes = Counter(item["change_type"] for item in changes[:100])
    return APIEnvelope(data={
        "competitor_id": row["id"],
        "name": row["canonical_name"],
        "normalized_name": row["normalized_name"],
        "official_domain": row["official_domain"],
        "status": row["status"],
        "source_statistics": {
            "total": int(row["source_count"]),
            "verified": int(row["verified_source_count"]),
        },
        "snapshot_statistics": {
            "total": int(row["snapshot_count"]),
            "successful": int(row["successful_snapshot_count"]),
        },
        "current_fact_categories": dict(categories),
        "recent_change_statistics": dict(recent_changes),
        "latest_run": _sanitize(latest_run),
        "latest_report": _sanitize(latest_report),
        "updated_at": row["updated_at"],
    })


@router.get("/competitors/{competitor_id}/sources", response_model=APIEnvelope)
def competitor_sources(request: Request, competitor_id: int) -> APIEnvelope:
    _require_competitor(request, competitor_id)
    with request.app.state.persistence.transaction() as session:
        rows = request.app.state.persistence.dashboard.list_sources(
            session, competitor_id
        )
    return APIEnvelope(data={"items": [_source_view(row) for row in rows]})


@router.get("/competitors/{competitor_id}/facts", response_model=APIEnvelope)
def competitor_facts(
    request: Request,
    competitor_id: int,
    category: str | None = Query(default=None, max_length=30),
) -> APIEnvelope:
    _require_competitor(request, competitor_id)
    with request.app.state.persistence.transaction() as session:
        rows = request.app.state.persistence.fact_versions.list_current(
            session, competitor_id
        )
    if category:
        rows = [row for row in rows if row["fact_category"] == category.upper()]
    return APIEnvelope(data={"items": [{
        "fact_id": row["id"],
        "category": row["fact_category"],
        "fact_key": row["fact_key"],
        "display_value": formatter.format(
            row["fact_category"], row["normalized_value"],
            fact_key=row["fact_key"], value_text=row.get("value_text"),
        ),
        "structured_value": decode_json(row["normalized_value"]),
        "confidence": float(row["confidence"]),
        "evidence_excerpt": row["evidence_text"][:500],
        "source_url": row["source_url"],
        "valid_from": row["valid_from"],
        "is_current": bool(row["is_current"]),
    } for row in rows]})


@router.get("/competitors/{competitor_id}/changes", response_model=APIEnvelope)
def competitor_changes(
    request: Request,
    competitor_id: int,
    run_id: int | None = None,
    change_type: str | None = Query(default=None, max_length=30),
    category: str | None = Query(default=None, max_length=30),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
) -> APIEnvelope:
    _require_competitor(request, competitor_id)
    with request.app.state.persistence.transaction() as session:
        rows = request.app.state.persistence.changes.list_for_competitor(
            session, competitor_id
        )
        fact_ids = {
            item for row in rows for item in (row["new_fact_id"], row["old_fact_id"])
            if item is not None
        }
        facts = {
            fact_id: request.app.state.persistence.product_facts.get(session, fact_id)
            for fact_id in fact_ids
        }
    if run_id is not None:
        rows = [row for row in rows if row["run_id"] == run_id]
    if change_type:
        rows = [row for row in rows if row["change_type"] == change_type.upper()]
    if category:
        rows = [
            row for row in rows
            if row["fact_key"].split(".", 1)[0].upper() == category.upper()
        ]
    items = []
    for row in rows[offset:offset + limit]:
        category_name = row["fact_key"].split(".", 1)[0].upper()
        old_display, new_display = formatter.format_change(
            category_name, row["fact_key"], row["old_value"], row["new_value"]
        )
        fact = facts.get(row["new_fact_id"]) or facts.get(row["old_fact_id"]) or {}
        items.append({
            "change_id": row["id"], "run_id": row["run_id"],
            "change_type": (
                "UNCOMPARABLE" if row["change_type"] == "UNKNOWN"
                else row["change_type"]
            ),
            "category": category_name, "fact_key": row["fact_key"],
            "old_display_value": old_display, "new_display_value": new_display,
            "old_value": decode_json(row["old_value"]),
            "new_value": decode_json(row["new_value"]),
            "reason": row["impact_assessment"],
            "confidence": float(row["confidence"]) if row["confidence"] is not None else None,
            "source_url": fact.get("source_url"),
            "detected_at": row["created_at"],
        })
    return APIEnvelope(data={"items": items, "limit": limit, "offset": offset})


@router.get("/competitors/{competitor_id}/reports", response_model=APIEnvelope)
def competitor_reports(request: Request, competitor_id: int) -> APIEnvelope:
    _require_competitor(request, competitor_id)
    with request.app.state.persistence.transaction() as session:
        rows = request.app.state.persistence.dashboard.list_reports(
            session, competitor_id
        )
    return APIEnvelope(data={"items": [{
        "report_id": row["id"], "run_id": row["run_id"],
        "report_type": row["report_type"], "status": row["status"],
        "created_at": row["generated_at"],
        "summary": _sanitize(decode_json(row["summary_json"]) or {}),
    } for row in rows]})


@router.get("/reports/{report_id}", response_model=APIEnvelope)
def report_detail(request: Request, report_id: int) -> APIEnvelope:
    report = CompetitorReportService(request.app.state.persistence).get(
        report_id=report_id
    )
    if not report:
        raise _error(404, "REPORT_NOT_FOUND", "Report was not found.")
    with request.app.state.persistence.transaction() as session:
        record = request.app.state.persistence.reports.get(session, report_id)
    return APIEnvelope(data={
        "report_id": report.report_id, "report_type": report.report_type,
        "title": report.title, "executive_summary": report.executive_summary,
        "change_summary": report.change_summary,
        "content_json": _sanitize(report.content_json),
        "content_markdown": report.content_markdown[:200_000],
        "created_at": record["generated_at"] if record else None,
    })


@router.get("/reports/{report_id}/download")
def report_download(
    request: Request,
    report_id: int,
    format: str = Query(default="markdown"),
) -> Response:
    if format != "markdown":
        raise _error(422, "INVALID_FORMAT", "Only markdown download is supported.")
    report = CompetitorReportService(request.app.state.persistence).get(
        report_id=report_id
    )
    if not report:
        raise _error(404, "REPORT_NOT_FOUND", "Report was not found.")
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", report.title).strip("-")[:80] or "report"
    return Response(
        report.content_markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{safe}.md"'},
    )


@router.get("/runs", response_model=APIEnvelope)
def runs(
    request: Request,
    competitor_id: int | None = None,
    state: str | None = Query(default=None, max_length=40),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
) -> APIEnvelope:
    with request.app.state.persistence.transaction() as session:
        rows = request.app.state.persistence.dashboard.list_runs(
            session, competitor_id=competitor_id, state=state,
            limit=limit, offset=offset,
        )
        items = []
        for row in rows:
            calls = request.app.state.persistence.tool_calls.list_for_run(
                session, row["id"]
            )
            items.append(_run_view(row, calls))
    return APIEnvelope(data={"items": items, "limit": limit, "offset": offset})


@router.get("/runs/{run_id}", response_model=APIEnvelope)
def run_detail(request: Request, run_id: int) -> APIEnvelope:
    with request.app.state.persistence.transaction() as session:
        row = request.app.state.persistence.dashboard.run_detail(session, run_id)
        calls = (
            request.app.state.persistence.tool_calls.list_for_run(session, run_id)
            if row else []
        )
        snapshots = (
            request.app.state.persistence.snapshots.list_for_run(session, run_id)
            if row else []
        )
        events = (
            request.app.state.persistence.stage_events.list_for_run(session, run_id)
            if row else []
        )
    if not row:
        raise _error(404, "RUN_NOT_FOUND", "Run was not found.")
    data = _run_view(row, calls)
    if row["status"] == "RUNNING" and events:
        details = decode_json(events[-1].get("details_json")) or {}
        data["current_state"] = details.get("logical_state", data["current_state"])
    data["snapshot_count"] = len(snapshots)
    data["snapshot_statuses"] = dict(Counter(item["fetch_status"] for item in snapshots))
    return APIEnvelope(data=data)


@router.get("/runs/{run_id}/events", response_model=APIEnvelope)
def run_events(request: Request, run_id: int) -> APIEnvelope:
    with request.app.state.persistence.transaction() as session:
        if not request.app.state.persistence.agent_runs.get(session, run_id):
            raise _error(404, "RUN_NOT_FOUND", "Run was not found.")
        rows = request.app.state.persistence.stage_events.list_for_run(session, run_id)
    return APIEnvelope(data={"items": [_event_view(row) for row in rows]})


@router.get("/runs/{run_id}/tool-calls", response_model=APIEnvelope)
def run_tool_calls(request: Request, run_id: int) -> APIEnvelope:
    with request.app.state.persistence.transaction() as session:
        if not request.app.state.persistence.agent_runs.get(session, run_id):
            raise _error(404, "RUN_NOT_FOUND", "Run was not found.")
        rows = request.app.state.persistence.tool_calls.list_for_run(session, run_id)
    return APIEnvelope(data={"items": [_tool_call_view(row) for row in rows]})


@router.get("/workspace/runs/{run_id}", response_model=APIEnvelope)
def workspace_run(request: Request, run_id: int) -> APIEnvelope:
    """Return a bounded, sanitized projection for deterministic run replay."""
    with request.app.state.persistence.transaction() as session:
        row = request.app.state.persistence.dashboard.run_detail(session, run_id)
        if not row:
            raise _error(404, "RUN_NOT_FOUND", "Run was not found.")
        raw_calls = request.app.state.persistence.tool_calls.list_for_run(
            session, run_id
        )
        raw_events = request.app.state.persistence.stage_events.list_for_run(
            session, run_id
        )
        snapshots = request.app.state.persistence.snapshots.list_for_run(
            session, run_id
        )
        competitor_id = row.get("competitor_id")
        competitor = (
            request.app.state.persistence.dashboard.competitor_overview(
                session, competitor_id
            )
            if competitor_id else None
        )
        raw_sources = (
            request.app.state.persistence.dashboard.list_sources(
                session, competitor_id
            )
            if competitor_id else []
        )
        raw_facts = (
            request.app.state.persistence.fact_observations.list_for_run(
                session, run_id
            )
            if competitor_id else []
        )
        raw_changes = (
            [
                change
                for change in request.app.state.persistence.changes.list_for_competitor(
                    session, competitor_id
                )
                if change["run_id"] == run_id
            ]
            if competitor_id else []
        )
        report_record = next(
            (
                report
                for report in request.app.state.persistence.dashboard.list_reports(
                    session, competitor_id
                )
                if report["run_id"] == run_id
            ),
            None,
        ) if competitor_id else None

    calls = [_tool_call_view(call) for call in raw_calls[:40]]
    events = [_event_view(event) for event in raw_events[:80]]
    run = _run_view(row, raw_calls)
    if row["status"] == "RUNNING" and events:
        run["current_state"] = events[-1]["stage"]
    run["snapshot_count"] = len(snapshots)
    run["snapshot_statuses"] = dict(
        Counter(snapshot["fetch_status"] for snapshot in snapshots)
    )
    run["page_comparison_summary"] = _page_comparison_summary(raw_calls)
    run["progress_percent"] = progress_for_events(
        events, run.get("final_state") or run["current_state"]
    )

    sources = [_source_view(source) for source in raw_sources[:50]]
    facts = [
        {
            "fact_id": fact["id"],
            "category": fact["fact_category"],
            "fact_key": fact["fact_key"],
            "display_value": formatter.format(
                fact["fact_category"],
                fact["normalized_value"],
                fact_key=fact["fact_key"],
                value_text=fact.get("value_text"),
            ),
            "confidence": float(fact["observed_confidence"]),
            "evidence_excerpt": fact["observed_evidence"][:500],
            "source_url": fact["observed_source_url"],
        }
        for fact in raw_facts[:100]
    ]
    changes = []
    for change in raw_changes[:100]:
        category = change["fact_key"].split(".", 1)[0].upper()
        old_display, new_display = formatter.format_change(
            category, change["fact_key"], change["old_value"], change["new_value"]
        )
        changes.append(
            {
                "change_id": change["id"],
                "change_type": (
                    "UNCOMPARABLE"
                    if change["change_type"] == "UNKNOWN"
                    else change["change_type"]
                ),
                "category": category,
                "fact_key": change["fact_key"],
                "old_display_value": old_display,
                "new_display_value": new_display,
                "evidence_excerpt": (change.get("evidence_text") or "")[:500],
                "reason": (change.get("impact_assessment") or "")[:500],
            }
        )

    report = None
    if report_record:
        rendered = CompetitorReportService(request.app.state.persistence).get(
            report_id=report_record["id"]
        )
        if rendered:
            report = {
                "report_id": rendered.report_id,
                "report_type": rendered.report_type,
                "title": rendered.title,
                "executive_summary": rendered.executive_summary,
                "change_summary": _sanitize(rendered.change_summary),
                "download_url": (
                    f"/api/reports/{rendered.report_id}/download?format=markdown"
                ),
            }

    messages = build_message_stream(
        run=run,
        events=events,
        calls=calls,
        sources=sources,
        facts=facts,
        changes=changes,
        report=report,
    )
    return APIEnvelope(
        data={
            "run": run,
            "competitor": _sanitize(competitor) if competitor else None,
            "messages": messages[:30],
            "events": events,
            "tool_calls": calls,
            "sources": sources,
            "facts": facts,
            "changes": changes,
            "report": report,
            "provider_summary": run["provider_summary"],
            "fact_extraction_status": run.get("fact_extraction_status"),
        }
    )


@router.post("/analyses", response_model=AnalysisAccepted, status_code=202)
def start_analysis(request: Request, payload: AnalysisRequest) -> AnalysisAccepted:
    try:
        run_id = request.app.state.task_manager.start(payload)
    except AnalysisAlreadyRunning:
        raise _error(
            409, "ANALYSIS_ALREADY_RUNNING",
            "An analysis is already running for this competitor.",
        )
    except AnalysisCapacityReached:
        raise _error(
            409, "ANALYSIS_CAPACITY_REACHED",
            "The local concurrent analysis limit has been reached.",
        )
    except (AnalysisStartFailed, ValueError) as exc:
        raise _error(500, "ANALYSIS_START_FAILED", str(exc))
    return AnalysisAccepted(
        run_id=run_id,
        status_url=f"/api/runs/{run_id}",
        events_url=f"/api/runs/{run_id}/events",
    )

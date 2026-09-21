"""Read-only product APIs. All database access stays behind Persistence."""

from datetime import date
from typing import Literal

from fastapi import APIRouter, Query, Request

from .router import _error, _source_view
from .schemas import APIEnvelope
from competitive_intel.web.intelligence import (
    CommandCenterPresenter, CompetitorProfilePresenter, SignalPresenter,
    parse_analyst_command, public_url,
)

router = APIRouter(prefix="/api")


@router.get("/command-center", response_model=APIEnvelope)
def command_center(request: Request, limit: int = Query(12, ge=1, le=100),
                   offset: int = Query(0, ge=0, le=10000)):
    store = request.app.state.persistence
    with store.transaction() as session:
        metrics = store.dashboard.intelligence_metrics(session)
        cards = store.dashboard.intelligence_cards(session, limit=limit, offset=offset)
        attention = store.dashboard.intelligence_cards(session, limit=limit, offset=offset, attention=True)
        signals = store.dashboard.signals(session, limit=limit, offset=0)
    return APIEnvelope(data={"metrics": metrics,
        "competitors": [CommandCenterPresenter.card(row) for row in cards],
        "attention": [CommandCenterPresenter.card(row) for row in attention],
        "recent_signals": [SignalPresenter.present(row) for row in signals],
        "limit": limit, "offset": offset})


@router.get("/signals", response_model=APIEnvelope)
def signals(request: Request, competitor_id: int | None = None,
            category: Literal["Pricing", "Product", "Feature", "Positioning", "Website", "Source", "Other"] | None = None,
            change_type: Literal["ADDED", "MODIFIED", "REMOVED", "UNCOMPARABLE", "UNCHANGED"] | None = None,
            start: date | None = None, end: date | None = None,
            status: Literal["confirmed", "needs_review"] | None = None,
            history: bool = False, limit: int = Query(20, ge=1, le=100),
            offset: int = Query(0, ge=0, le=10000)):
    if start and end and start > end:
        raise _error(422, "INVALID_RANGE", "Start date must not follow end date.")
    store = request.app.state.persistence
    with store.transaction() as session:
        rows = store.dashboard.signals(session, competitor_id=competitor_id,
            category=category, change_type="UNKNOWN" if change_type == "UNCOMPARABLE" else change_type,
            start=start, end=end, status=status, history=history, limit=limit + 1, offset=offset)
    return APIEnvelope(data={"items": [SignalPresenter.present(row) for row in rows[:limit]],
                             "has_more": len(rows) > limit, "limit": limit, "offset": offset})


@router.get("/competitors/{competitor_id}/intelligence", response_model=APIEnvelope)
def profile(request: Request, competitor_id: int, limit: int = Query(50, ge=1, le=100),
            offset: int = Query(0, ge=0, le=10000),
            fact_category: Literal["Pricing", "Feature"] | None = None):
    store = request.app.state.persistence
    with store.transaction() as session:
        cards = store.dashboard.intelligence_cards(session, competitor_id=competitor_id, limit=1, offset=0)
        if not cards:
            raise _error(404, "COMPETITOR_NOT_FOUND", "Competitor was not found.")
        facts = store.dashboard.intelligence_facts(session, competitor_id, limit=limit + 1, offset=offset, category=fact_category)
        sources = store.dashboard.list_sources(session, competitor_id, limit=limit + 1, offset=offset)
        reports = store.dashboard.intelligence_reports(session, competitor_id=competitor_id, limit=limit + 1, offset=offset)
    views = []
    for row in sources[:limit]:
        view = _source_view(row)
        view["url"] = public_url(view["url"])
        views.append(view)
    return APIEnvelope(data={"competitor": CommandCenterPresenter.card(cards[0]),
        "facts": [CompetitorProfilePresenter.fact(row) for row in facts[:limit]],
        "sources": views, "reports": reports[:limit],
        "has_more": any(len(rows) > limit for rows in (facts, sources, reports)),
        "has_more_facts": len(facts) > limit, "has_more_sources": len(sources) > limit,
        "has_more_reports": len(reports) > limit,
        "limit": limit, "offset": offset})


@router.get("/reports", response_model=APIEnvelope)
def reports(request: Request, competitor_id: int | None = None,
            limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0, le=10000)):
    store = request.app.state.persistence
    with store.transaction() as session:
        rows = store.dashboard.intelligence_reports(session, competitor_id=competitor_id, limit=limit + 1, offset=offset)
    return APIEnvelope(data={"items": rows[:limit], "has_more": len(rows) > limit, "limit": limit, "offset": offset})


@router.get("/analyst/command", response_model=APIEnvelope)
def analyst_command(text: str = Query(min_length=1, max_length=250)):
    return APIEnvelope(data=parse_analyst_command(text))

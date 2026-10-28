"""Formal Chat entrypoint for existing evidence, with no search/extraction path."""
import os
import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from competitive_intel.api.schemas import APIEnvelope
from competitive_intel.infrastructure.agent.narrative_writer import isolated_budget, reviewed_rates
from competitive_intel.services.research_context import ResearchContext
from competitive_intel.services.saved_evidence_writing import saved_scope, PinnedFixtureWriter, StoredCandidateWriter
from competitive_intel.services.competitive_report_service import CompetitiveReportService
from competitive_intel.services.task_understanding_service import output_language

router = APIRouter(prefix="/api/analyst/saved-writing")


class SavedWritingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_id: int = Field(gt=0)
    text: str = Field(min_length=3, max_length=1000)
    request_id: UUID
    allow_paid: bool = False


@router.post("", response_model=APIEnvelope)
def write_saved(payload: SavedWritingRequest, request: Request):
    p = request.app.state.persistence
    try:
        task, products = saved_scope(p, payload.report_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    # This MVP explicitly retains the source scope, rather than pretending to
    # understand arbitrary new competitors or dimensions without an interpreter.
    if not all(name.casefold() in payload.text.casefold() for name in [task.target, *task.competitors]):
        raise HTTPException(422, "SAVED_SCOPE_PRODUCT_NAMES_REQUIRED")
    task = task.model_copy(update={"output_language": output_language(payload.text)})
    factory = getattr(request.app.state, "saved_writer_context_factory", None)
    if factory:
        context = factory()
    elif os.getenv("REPORT_WRITER_REVIEWS") and not payload.allow_paid:
        context = ResearchContext(request.app.state.settings, budget=isolated_budget(), rates=reviewed_rates())
        context.report_writer = StoredCandidateWriter(p, payload.report_id)
        context.writing_reviews = json.loads(Path(os.environ["REPORT_WRITER_REVIEWS"]).read_text(encoding="utf-8"))
    elif os.getenv("REPORT_WRITER_FIXTURE") and not payload.allow_paid:
        context = ResearchContext(request.app.state.settings, budget=isolated_budget(), rates=reviewed_rates())
        context.report_writer = PinnedFixtureWriter(os.environ["REPORT_WRITER_FIXTURE"])
        context.writing_reviews = context.report_writer.reviews
    elif payload.allow_paid and os.getenv("AI_REPORT_WRITER_ENABLED") == "1":
        context = ResearchContext(request.app.state.settings, allow_paid=True,
                                  budget=isolated_budget(), rates=reviewed_rates())
        attempt_dir = Path("build/writing-attempts")
        attempt_dir.mkdir(parents=True, exist_ok=True)
        context.enable_report_writer(attempt_dir / (str(payload.request_id) + ".json"))
    else:
        raise HTTPException(403, "WRITER_NOT_CONFIGURED_OR_LIVE_NOT_AUTHORIZED")
    context.budget.task_id = str(payload.request_id)
    context.writing_goal = payload.text
    context.source_report_id = payload.report_id
    try:
        result = CompetitiveReportService(p).run(task, products, context)
        return APIEnvelope(data=result)
    except ValueError:
        raise HTTPException(409, "SAVED_WRITING_SCOPE_CONFLICT") from None
    finally:
        context.close()

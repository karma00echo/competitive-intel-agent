"""Discovery entrypoint on the existing application, not a parallel demo."""

import json
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from competitive_intel.api.schemas import APIEnvelope
from competitive_intel.domain.analysis_task import AnalysisTaskSpec
from competitive_intel.domain.task_budget import BudgetExhausted
from competitive_intel.infrastructure.budgeted_transport import CostRates
from competitive_intel.services.agent_runner import AgentRunner
from competitive_intel.services.competitor_discovery import CompetitorDiscoveryService
from competitive_intel.services.research_context import ResearchContext
from competitive_intel.services.task_understanding_service import TaskUnderstandingService


router = APIRouter(prefix="/api")


@router.get("/analyst/discover/{run_id}", response_model=APIEnvelope)
def discovery_result(run_id: int, request: Request):
    with request.app.state.persistence.transaction() as session:
        calls = request.app.state.persistence.tool_calls.list_for_run(session, run_id)
    for call in calls:
        if call["tool_name"] == "discover_competitors" and call["output_summary"]:
            return APIEnvelope(data=json.loads(call["output_summary"]))
    raise HTTPException(404, detail="DISCOVERY_RESULT_NOT_FOUND")


class DiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task: AnalysisTaskSpec | None = None
    text: str | None = Field(default=None, min_length=1, max_length=1000)
    allow_paid: bool = False

    @model_validator(mode="after")
    def one_input(self):
        if (self.task is None) == (self.text is None):
            raise ValueError("Provide either a validated task or natural-language text")
        return self


@router.post("/analyst/discover", response_model=APIEnvelope)
def discover(payload: DiscoveryRequest, request: Request):
    if not payload.allow_paid:
        raise HTTPException(403, detail="Explicit paid provider consent is required; no request was sent.")
    try:
        rates = CostRates.from_env()
    except ValueError:
        raise HTTPException(503, detail="RESEARCH_COST_RATES_REQUIRED") from None
    context = ResearchContext(request.app.state.settings, allow_paid=True, rates=rates)
    try:
        interpretation_audit = None
        task = payload.task
        if task is None:
            interpreted = TaskUnderstandingService(context.understanding_provider()).interpret(payload.text)
            if interpreted["status"] != "READY":
                return APIEnvelope(data={**interpreted, "phase": "task_understanding",
                                         "budget": context.budget.snapshot(), "analysis_complete": False})
            task = AnalysisTaskSpec.model_validate(interpreted["task"])
            interpretation_audit = interpreted["audit"]
        service = CompetitorDiscoveryService(context, context.search_provider(), context.page_fetcher(), context.candidate_evaluator())
        service.interpretation_audit = interpretation_audit
        return APIEnvelope(data=AgentRunner.discover_competitors(request.app.state.persistence, task, service))
    except BudgetExhausted as exc:
        return APIEnvelope(data={"status": "PARTIAL", "error_code": str(exc),
                                 "budget": context.budget.snapshot(), "analysis_complete": False})
    finally:
        context.close()

"""Formal application entrypoint; no implicit fixture fallback or paid execution."""

import os
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from competitive_intel.api.schemas import APIEnvelope
from competitive_intel.domain.competitive_matrix import decode
from competitive_intel.domain.task_budget import BudgetLimits
from competitive_intel.infrastructure.budgeted_transport import CostRates
from competitive_intel.services.agent_runner import AgentRunner
from competitive_intel.services.research_context import ResearchContext
from competitive_intel.web.runtime import AnalysisAlreadyRunning, AnalysisCapacityReached

router = APIRouter(prefix="/api/analyst/workflows")


class WorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    text: str = Field(min_length=1, max_length=1000)
    allow_paid: bool = False


@router.get("/readiness", response_model=APIEnvelope)
def readiness(request: Request):
    reasons = []
    try:
        with request.app.state.persistence.transaction() as tx:
            request.app.state.persistence.reports.require_competitive_schema(tx)
    except Exception:
        reasons.append("DATABASE_004_REQUIRED_OR_UNAVAILABLE")
    if os.getenv("WORKFLOW_PAID_ENABLED") != "1":
        reasons.append("PAID_WORKFLOW_DISABLED")
    cfg = request.app.state.settings
    if not all([cfg.search.api_key, cfg.llm.api_key, cfg.llm.model, cfg.llm.endpoint]):
        reasons.append("PROVIDER_CONFIGURATION_REQUIRED")
    try:
        CostRates.from_env()
    except ValueError:
        reasons.append("REVIEWED_COST_RATES_REQUIRED")
    return APIEnvelope(data={"ready": not reasons, "blockers": reasons, "limits": vars(BudgetLimits())})


@router.post("", response_model=APIEnvelope, status_code=202)
def start(payload: WorkflowRequest, request: Request):
    if not payload.allow_paid or os.getenv("WORKFLOW_PAID_ENABLED") != "1":
        raise HTTPException(403, detail="PAID_WORKFLOW_DISABLED_OR_NOT_CONSENTED")
    state = readiness(request).data
    if not state["ready"]:
        raise HTTPException(503, detail=", ".join(state["blockers"]))
    factory = getattr(request.app.state, "workflow_context_factory", None)
    context = factory() if factory else ResearchContext(request.app.state.settings, allow_paid=True, rates=CostRates.from_env())
    try:
        workflow = AgentRunner.workflow(request.app.state.persistence, context)
        rid = request.app.state.task_manager.start_workflow(payload.text, workflow)
    except (AnalysisAlreadyRunning, AnalysisCapacityReached):
        context.close()
        raise HTTPException(409, detail="WORKFLOW_ALREADY_RUNNING_OR_CAPACITY_REACHED") from None
    except Exception:
        context.close()
        raise
    return APIEnvelope(data={"run_id": rid, "status": "RUNNING"})


@router.get("/{run_id}", response_model=APIEnvelope)
def get(run_id: int, request: Request):
    with request.app.state.persistence.transaction() as tx:
        calls = request.app.state.persistence.tool_calls.list_for_run(tx, run_id)
    for call in calls:
        if call["tool_name"] == "run_competitive_workflow":
            return APIEnvelope(data=decode(call["output_summary"]))
    raise HTTPException(404, detail="WORKFLOW_NOT_FOUND")

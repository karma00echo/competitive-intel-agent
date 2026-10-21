"""Standalone task-preview endpoint with no persistence dependencies."""

from fastapi import APIRouter, Request

from competitive_intel.api.schemas import APIEnvelope
from competitive_intel.domain.analysis_task import InterpretTaskRequest
from competitive_intel.infrastructure.agent.task_understanding import (
    FixtureTaskUnderstandingProvider, LLMTaskUnderstandingProvider,
)
from competitive_intel.services.task_understanding_service import TaskUnderstandingService

router = APIRouter(prefix="/api")


@router.post("/analyst/interpret", response_model=APIEnvelope)
def interpret_task(payload: InterpretTaskRequest, request: Request):
    """Explicit provider selection; no runner, database, search or report side effects."""
    provider = (FixtureTaskUnderstandingProvider() if payload.provider == "fixture"
                else LLMTaskUnderstandingProvider(request.app.state.settings.llm))
    return APIEnvelope(data=TaskUnderstandingService(provider).interpret(payload.text))

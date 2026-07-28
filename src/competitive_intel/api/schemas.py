"""Stable Pydantic contracts for the local API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class APIEnvelope(BaseModel):
    ok: bool = True
    data: Any


class ErrorBody(BaseModel):
    ok: bool = False
    error_code: str
    error_message: str


class HealthResponse(BaseModel):
    status: str
    database_status: str
    app_version: str
    fixture_available: bool
    serper_configured: bool
    active_task_count: int


class AnalysisRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    competitor_name: str = Field(min_length=1, max_length=120)
    language: Literal["en", "zh"] | None = None
    locale: str = Field(default="en-US", min_length=2, max_length=20)
    search_provider: Literal["fixture", "serper"] = "fixture"
    fact_provider: Literal["fixture"] = "fixture"
    agent_provider: Literal["fixture"] = "fixture"
    fixture_scenario: Literal[
        "default", "unchanged", "price_changed", "feature_added",
        "feature_removed", "page_failure"
    ] = "default"
    skip_fact_extraction: bool = False
    max_tool_calls: int = Field(default=20, ge=4, le=40)

    @field_validator("competitor_name")
    @classmethod
    def reject_control_characters(cls, value: str) -> str:
        if any(ord(character) < 32 for character in value):
            raise ValueError("competitor_name contains control characters")
        return value

    @model_validator(mode="after")
    def real_content_isolation(self) -> "AnalysisRequest":
        if self.search_provider == "serper" and not self.skip_fact_extraction:
            raise ValueError(
                "Serper real-content mode requires skip_fact_extraction=true "
                "until a real fact provider is implemented."
            )
        return self


class AnalysisAccepted(BaseModel):
    run_id: int
    status: Literal["ACCEPTED"] = "ACCEPTED"
    status_url: str
    events_url: str

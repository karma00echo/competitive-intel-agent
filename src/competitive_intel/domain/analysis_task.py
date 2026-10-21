"""Task understanding only: a plan is not a fact, report, or executable tool call."""

from typing import Literal
import unicodedata

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Dimension = Literal["positioning", "target_users", "core_features", "ai_capabilities", "pricing", "differentiation"]
DEFAULT_DIMENSIONS = ["positioning", "target_users", "core_features", "ai_capabilities", "pricing", "differentiation"]


class AnalysisTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    status: Literal["READY", "NEEDS_CLARIFICATION", "UNSUPPORTED"]
    target: str | None = Field(max_length=120)
    intent: Literal["competitive_analysis", "comparison", "product_analysis"]
    competitors: list[str] = Field(max_length=2)
    dimensions: list[Dimension] = Field(max_length=6)
    output_format: Literal["report", "table", "brief"]
    discover_competitors: bool
    assumptions: list[str] = Field(max_length=5)
    clarification: str | None = Field(max_length=300)

    @field_validator("target")
    @classmethod
    def product_name(cls, value):
        if value is not None:
            if not value or len(value) > 120 or any(unicodedata.category(c).startswith("C") for c in value):
                raise ValueError("Invalid product name")
            if "://" in value or value.startswith("www."):
                raise ValueError("Product names, not URLs, are required")
        return value

    @field_validator("competitors")
    @classmethod
    def competitor_names(cls, values):
        for value in values:
            cls.product_name(value)
            if value != value.strip():
                raise ValueError("Product names must be trimmed")
        if len({v.casefold() for v in values}) != len(values):
            raise ValueError("Duplicate competitors")
        return values

    @field_validator("assumptions")
    @classmethod
    def bounded_assumptions(cls, values):
        if any(not v.strip() or len(v) > 300 for v in values):
            raise ValueError("Invalid assumption")
        return values

    @model_validator(mode="after")
    def consistent_plan(self):
        if len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("Duplicate dimensions")
        if self.target and self.target.casefold() in {v.casefold() for v in self.competitors}:
            raise ValueError("Target cannot compete with itself")
        if self.status == "READY":
            if not self.target or not self.dimensions or self.clarification:
                raise ValueError("Ready task requires target and dimensions, without clarification")
            if self.intent == "comparison" and not self.competitors:
                raise ValueError("Explicit comparison requires competitors")
        elif not self.clarification or not self.clarification.strip():
            raise ValueError("Unresolved task requires an explanation or clarification")
        if self.intent == "product_analysis" and (self.competitors or self.discover_competitors):
            raise ValueError("Single product scope cannot discover competitors")
        if self.competitors and self.discover_competitors:
            raise ValueError("MVP does not expand explicitly supplied competitors")
        return self


class InterpretTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=1000)
    provider: Literal["fixture", "openai_compatible"] = "fixture"

    @field_validator("text")
    @classmethod
    def safe_text(cls, value):
        if any(unicodedata.category(c).startswith("C") and c not in "\n\t" for c in value):
            raise ValueError("Control characters are not permitted")
        return value

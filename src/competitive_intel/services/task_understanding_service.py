"""Validate a single interpretation without starting or persisting an analysis."""

import re

from pydantic import ValidationError

from competitive_intel.domain.analysis_task import AnalysisTaskSpec, InterpretTaskRequest
from competitive_intel.infrastructure.agent.task_understanding import PROMPT_VERSION, TaskUnderstandingProvider


class TaskUnderstandingService:
    def __init__(self, provider: TaskUnderstandingProvider):
        self.provider = provider

    def interpret(self, text: str) -> dict:
        request = InterpretTaskRequest(text=text)
        result = self.provider.interpret(request.text)
        audit = {"provider": self.provider.name, "prompt_version": PROMPT_VERSION,
                 "model": getattr(self.provider, "model", None),
                 "attempts": result.attempts, "usage": result.usage or None,
                 "duration_ms": result.duration_ms, "execution_started": False}
        if result.error:
            return {"status": "FAILED", "task": None, "error_code": result.error, "audit": audit}
        try:
            task = AnalysisTaskSpec.model_validate(result.payload)
            # Explicit language directives override input-language defaults. This
            # changes presentation only, never the language of collected evidence.
            if re.search(r"(?:用|以|使用)英文|英文(?:报告|输出)|(?:report|respond|write|output).*?in English", request.text, re.I):
                task.output_language = "en"
            elif re.search(r"(?:用|以|使用)中文|中文(?:报告|输出)|(?:report|respond|write|output).*?in Chinese", request.text, re.I):
                task.output_language = "zh-CN"
            else:
                task.output_language = "zh-CN" if re.search(r"[\u4e00-\u9fff]", request.text) else "en"
            # Names must come from the request; automatic discovery happens later.
            for name in ([task.target] if task.target else []) + task.competitors:
                if name.casefold() not in request.text.casefold():
                    raise ValueError("Invented product")
                if re.search(r"^(?:帮我|请)?(?:分析|比较|对比)|^(?:analyze|compare)\s|竞品|竞争对手|[，。！？]", name, re.I):
                    raise ValueError("Request mistaken for product")
        except (ValidationError, ValueError):
            return {"status": "FAILED", "task": None, "error_code": "INVALID_TASK_SPEC", "audit": audit}
        return {"status": task.status, "task": task.model_dump(), "error_code": None, "audit": audit}

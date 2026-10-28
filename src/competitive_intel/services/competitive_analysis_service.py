"""Analysis of a repository-built matrix using the caller's existing task budget."""

from competitive_intel.domain.competitive_findings import build_findings
from competitive_intel.domain.task_budget import BudgetExhausted


class CompetitiveAnalysisService:
    def analyze(self, matrix, context):
        supported = build_findings(matrix)
        result = {"schema_version": "competitive-analysis-v1", "matrix": matrix,
                  "supported_findings": supported["findings"], "conclusions": [],
                  "limitations": supported["limitations"], "status": "PARTIAL",
                  "synthesis_status": "NOT_RUN", "issues": [], "usage": None}
        if context.budget.exhausted:
            result["issues"].append("TASK_BUDGET_EXHAUSTED")
        elif not supported["findings"]:
            result["issues"].append("INSUFFICIENT_COMPARABLE_EVIDENCE")
        else:
            try:
                if getattr(context, "report_writer", None) is not None:
                    # All legal comparisons are supplied to the writer; no second
                    # paid ID-selection call, no independent/reset budget.
                    result["conclusions"] = supported["findings"]
                    result["synthesis_status"] = "DETERMINISTIC_CATALOG"
                else:
                    provider = context.synthesis_provider()
                    result["conclusions"] = provider.synthesize(supported)
                    result["usage"] = provider.usage
                    result["synthesis_status"] = "SUCCEEDED"
                comparison_gaps = any(item["code"] != "NO_COMPLETENESS_OR_SUITABILITY_RANKING"
                                      for item in supported["limitations"])
                if matrix["status"] == "COMPLETE" and not comparison_gaps:
                    result["status"] = "COMPLETE"
            except BudgetExhausted:
                result["synthesis_status"] = "BUDGET_EXHAUSTED"
                result["issues"].append("TASK_BUDGET_EXHAUSTED")
            except Exception:
                # Never persist provider exceptions containing credentials or page content.
                # Validated matrix survives; no conclusion is invented as a fallback.
                result["synthesis_status"] = "FAILED"
                result["issues"].append("SYNTHESIS_FAILED")
        result["budget"] = context.budget.snapshot()
        return result

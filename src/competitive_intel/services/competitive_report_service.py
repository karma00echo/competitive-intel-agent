"""Persist evidence-only cross-product reports through the existing repositories."""

from dataclasses import asdict
from hashlib import sha256
from html import escape
import json

from competitive_intel.domain.competitive_matrix import decode
from .competitive_analysis_service import CompetitiveAnalysisService
from .competitive_matrix_service import CompetitiveMatrixService


def render_competitive_report(task, analysis):
    """Render the exact stored payload; source text never becomes markup."""
    def plain(value):
        return escape(str(value)).replace("\n", " ").replace("|", "&#124;").replace("`", "&#96;")

    matrix = analysis["matrix"]
    lines = [f"# Competitive analysis: {plain(task.target)}", "",
             f"Status: **{analysis['status']}**", "",
             "Facts are observed evidence; conclusions are analysis inferences. Missing data is not absence.", "",
             "## Fact matrix", "", "| Product | Dimension | Status | Facts |", "|---|---|---|---|"]
    for product in matrix["products"]:
        for dimension, cell in product["cells"].items():
            lines.append(f"| {plain(product['name'])} | {dimension} | {cell['status']} | {', '.join(cell['fact_ids'])} |")
    lines.extend(["", "## Observed facts and unresolved conflicts", ""])
    for fid, fact in matrix["facts"].items():
        lines.append(f"- {fid} — {plain(fact['product'])} ({fact['verification_status']}): "
                     f"{plain(json.dumps(fact['value'], ensure_ascii=False))}; evidence: {', '.join(fact['evidence_ids'])}")
    lines.extend(["", "## Supported comparisons", ""])
    for finding in analysis["supported_findings"]:
        lines.append(f"- {finding['id']} [ANALYSIS_INFERENCE]: {plain(finding['text'])} "
                     f"Facts: {', '.join(finding['fact_ids'])}; evidence: {', '.join(finding['evidence_ids'])}")
    lines.extend(["", "## Synthesis", "", f"Synthesis status: {analysis['synthesis_status']}", ""])
    lines.extend(f"- [ANALYSIS_INFERENCE] {plain(f['text'])} ({', '.join(f['evidence_ids'])})" for f in analysis["conclusions"])
    if not analysis["conclusions"]:
        lines.append("Information insufficient or synthesis unavailable; no generated conclusion.")
    lines.extend(["", "## Evidence", ""])
    for eid, evidence in matrix["evidence"].items():
        lines.append(f"- {eid}: {plain(evidence['url'])} — {plain(evidence['quote'])}; "
                     f"collected {evidence['collected_at']}; product {evidence['product_id']}, "
                     f"source {evidence['source_id']}, snapshot {evidence['snapshot_id']}, "
                     f"observation {evidence['observation_id']}, run {evidence['run_id']}")
    lines.extend(["", "## Limitations and gaps", ""])
    for gap in matrix["gaps"] + analysis["limitations"] + analysis["issues"]:
        lines.append("- " + plain(json.dumps(gap, ensure_ascii=False)))
    return "\n".join(lines) + "\n"


class CompetitiveReportService:
    def __init__(self, persistence):
        self.persistence = persistence

    def run(self, task, products, context):
        """Server-only handoff. Reusing a task ID returns its immutable execution.

        This consumes existing research observations; it does not start a new
        search workflow, accept client budgets or publish historical baselines.
        """
        if not products or not products[0].identity_verified or products[0].product_id is None:
            raise ValueError("VERIFIED_TARGET_REQUIRED")
        scope = {"task": task.model_dump(), "products": [asdict(p) for p in products]}
        signature = sha256(json.dumps(scope, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        p = self.persistence
        with p.transaction() as tx:
            p.reports.require_competitive_schema(tx)
            target = p.reports.lock_target(tx, products[0].product_id)
            if not target or target["normalized_name"] != task.target.casefold():
                raise ValueError("TARGET_IDENTITY_MISMATCH")
            existing = p.reports.get_comparison_task(tx, context.budget.task_id)
            if existing:
                if decode(existing["input_summary"])["signature"] != signature:
                    raise ValueError("TASK_SCOPE_CHANGED")
                return decode(existing["output_summary"])
            discovery_call = p.reports.get_discovery_task(tx, context.budget.task_id)
            discovery = decode(discovery_call["output_summary"]) if discovery_call else None
            if task.discover_competitors and not discovery:
                raise ValueError("TRUSTED_DISCOVERY_REQUIRED")
            if discovery:
                if (discovery.get("task") != task.model_dump()
                        or set(discovery["selected"]) != {product.name for product in products[1:]}):
                    raise ValueError("DISCOVERY_SCOPE_MISMATCH")
                budget = discovery["budget"]
                if (budget["limits"] != context.budget.snapshot()["limits"] or
                        any(context.budget.used[k] < v for k, v in budget["used"].items())):
                    raise ValueError("TASK_BUDGET_RESET")
            for product in products:
                if product.run_id is None:
                    continue
                run = p.agent_runs.get(tx, product.run_id)
                profile = p.competitors.get(tx, product.product_id) if product.product_id else None
                if (not run or run["competitor_id"] != product.product_id or not profile
                        or profile["normalized_name"] != product.name.casefold()):
                    raise ValueError("RESEARCH_IDENTITY_MISMATCH")
            run_id = p.agent_runs.create(tx, input_name=task.target, normalized_input=task.target.casefold(),
                competitor_id=products[0].product_id, run_mode="UNKNOWN", current_state="REPORT_GENERATION", max_tool_calls=1)
            stage_id = p.stage_events.create(tx, run_id=run_id, stage="REPORT_GENERATION", attempt_no=1, max_attempts=1,
                details={"phase": "competitive_analysis", "task_id": context.budget.task_id})
            call_id = p.tool_calls.create(tx, run_id=run_id, stage_event_id=stage_id, call_index=1,
                tool_name="compare_products", input_summary={**scope, "signature": signature, "task_id": context.budget.task_id})
            p.tool_calls.checkpoint(tx, call_id, output_summary={"phase": "competitive_analysis", "status": "RUNNING",
                "run_id": run_id, "report_id": None, "analysis_complete": False, "budget": context.budget.snapshot()})
        previous_checkpoint = context.budget.checkpoint

        def checkpoint(budget):
            if previous_checkpoint:
                previous_checkpoint(budget)
            with p.transaction() as tx:
                p.tool_calls.checkpoint(tx, call_id, output_summary={"phase": "competitive_analysis", "status": "RUNNING",
                    "run_id": run_id, "report_id": None, "analysis_complete": False, "budget": budget,
                    "research_policy": context.audit_policy()})

        context.budget.checkpoint = checkpoint
        try:
            matrix = CompetitiveMatrixService(p).build(task, products)
            if discovery and discovery["status"] != "READY":
                matrix["gaps"].append({"code": "DISCOVERY_INCOMPLETE"})
                matrix["status"] = "PARTIAL"
            analysis = CompetitiveAnalysisService().analyze(matrix, context)
            analysis.update(task=task.model_dump(), research_policy=context.audit_policy())
            analysis["discovery_run_id"] = discovery_call["run_id"] if discovery_call else None
            complete = analysis["status"] == "COMPLETE"
            report_type = "COMPETITIVE_ANALYSIS" if complete else "COMPETITIVE_ANALYSIS_PARTIAL"
            markdown = render_competitive_report(task, analysis)
            result = {"phase": "competitive_analysis", "status": analysis["status"], "run_id": run_id,
                      "analysis_complete": complete, "budget": context.budget.snapshot(), "report_id": None,
                      "research_policy": context.audit_policy(), "report_type": report_type}
            with p.transaction() as tx:
                result["report_id"] = p.reports.create(tx, competitor_id=products[0].product_id, run_id=run_id,
                    report_type=report_type, status="GENERATED", generator_version="competitive-report-v1",
                    content_markdown=markdown, summary={"report_type": report_type,
                        "title": f"Competitive analysis: {task.target}", "executive_summary": analysis["status"],
                        "content_json": analysis, "section_count": 6, "change_summary": {}, "warnings": analysis["issues"]})
                p.tool_calls.finish(tx, call_id, status="SUCCEEDED", output_summary=result)
                p.stage_events.finish(tx, stage_id, status="SUCCEEDED")
                p.agent_runs.finish(tx, run_id, status="COMPLETED" if complete else "PARTIAL_SUCCESS",
                                    current_state="COMPLETED", error_code=None if complete else "COMPETITIVE_ANALYSIS_PARTIAL")
            return result
        except Exception:
            result = {"phase": "competitive_analysis", "status": "FAILED", "run_id": run_id, "report_id": None,
                      "analysis_complete": False, "budget": context.budget.snapshot(), "issues": ["COMPARISON_FAILED"]}
            with p.transaction() as tx:
                p.tool_calls.finish(tx, call_id, status="FAILED", output_summary=result, error_code="COMPARISON_FAILED")
                p.stage_events.finish(tx, stage_id, status="FAILED")
                p.agent_runs.finish(tx, run_id, status="FAILED", current_state="FAILED", error_code="COMPARISON_FAILED")
            return result
        finally:
            context.budget.checkpoint = previous_checkpoint

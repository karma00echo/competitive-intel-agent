"""Persist evidence-only cross-product reports through the existing repositories."""

from dataclasses import asdict
from hashlib import sha256
from html import escape
import json
import re
from urllib.parse import quote, urlsplit

from competitive_intel.domain.competitive_matrix import decode
from competitive_intel.domain.analysis_task import AnalysisTaskSpec
from .competitive_analysis_service import CompetitiveAnalysisService
from .competitive_matrix_service import CompetitiveMatrixService


def render_competitive_report(task, analysis):
    """One persisted reading model drives Markdown and the formal UI."""
    from competitive_intel.domain.comparison_presentation import reading_view
    view = analysis.get("presentation") or reading_view(task, analysis)
    def plain(value):
        return escape(str(value)).replace("\n", " ").replace("|", "&#124;").replace("`", "&#96;").replace("[", "&#91;").replace("]", "&#93;")
    reference_labels = {e["label"] for e in view["references"]}
    def cited(value):
        parts = re.split(r"(\[\d+\])", str(value))
        return "".join(f"[{p[1:-1]}](#source-{p[1:-1]})" if re.fullmatch(r"\[\d+\]", p) and p[1:-1] in reference_labels else plain(p) for p in parts)
    lines = ["# " + plain(view["title"]), "", "**" + ("部分报告" if view["language"] == "zh-CN" and view["status"] != "COMPLETE" else view["status"]) + "**", ""]
    for section in view["sections"]:
        lines += ["## " + plain(section["heading"]), "", *[cited(p) + "\n" for p in section.get("paragraphs", [])], ""]
        if "headers" in section:
            lines.append("| " + " | ".join(plain(h) for h in section["headers"]) + " |")
            lines.append("| " + " | ".join("---" for _ in section["headers"]) + " |")
            lines.extend("| " + " | ".join(cited(c) for c in row) + " |" for row in section["rows"])
            lines.append("")
    lines += ["## " + ("证据来源（原文）" if view["language"] == "zh-CN" else "Sources (original quotations)"), ""]
    for evidence in view["references"]:
        url = evidence["url"]
        safe_url = quote(url, safe=":/?=&%#@+;,") if urlsplit(url).scheme in {"http", "https"} else "#"
        lines += [f'<a id="source-{plain(evidence["label"])}"></a>',
                  "- [" + evidence["label"] + "] [" + plain(url) + "](<" + safe_url + ">) — " + plain(evidence["collected_at"]),
                  *["> " + plain(line) for line in evidence["quote"].split("\n")], ""]
    lines += ["<details><summary>Technical audit / 技术详情</summary>", "", "```json",
              json.dumps({"gaps": view["gaps"], "writing": view.get("writing"), "facts": analysis["matrix"]["facts"], "evidence": analysis["matrix"]["evidence"]}, ensure_ascii=False, indent=2).replace("<", "\\u003c").replace("`", "\\u0060"), "```", "</details>"]
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
        if getattr(context, "report_writer", None) is not None:
            scope["writing_goal"] = context.writing_goal
            scope["source_report_id"] = getattr(context, "source_report_id", None)
        signature = sha256(json.dumps(scope, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        p = self.persistence
        with p.transaction() as tx:
            p.reports.require_competitive_schema(tx)
            target = p.reports.lock_target(tx, products[0].product_id)
            if not target or target["normalized_name"] != task.target.casefold():
                raise ValueError("TARGET_IDENTITY_MISMATCH")
            existing = p.reports.get_comparison_task(tx, context.budget.task_id)
            if existing:
                stored_scope = decode(existing["input_summary"])
                compatible_task = AnalysisTaskSpec.model_validate(stored_scope["task"]).model_dump()
                if (compatible_task != scope["task"] or stored_scope["products"] != json.loads(json.dumps(scope["products"]))
                        or stored_scope.get("writing_goal") != scope.get("writing_goal")
                        or stored_scope.get("source_report_id") != scope.get("source_report_id")):
                    raise ValueError("TASK_SCOPE_CHANGED")
                return decode(existing["output_summary"])
            discovery_call = p.reports.get_discovery_task(tx, context.budget.task_id)
            discovery = decode(discovery_call["output_summary"]) if discovery_call else None
            if task.discover_competitors and not discovery:
                raise ValueError("TRUSTED_DISCOVERY_REQUIRED")
            if discovery:
                if (AnalysisTaskSpec.model_validate(discovery["task"]).model_dump() != task.model_dump()
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
            analysis["source_report_id"] = getattr(context, "source_report_id", None)
            analysis["discovery_run_id"] = discovery_call["run_id"] if discovery_call else None
            complete = analysis["status"] == "COMPLETE"
            report_type = "COMPETITIVE_ANALYSIS" if complete else "COMPETITIVE_ANALYSIS_PARTIAL"
            from competitive_intel.domain.comparison_presentation import reading_view
            if getattr(context, "report_writer", None) is not None:
                from competitive_intel.domain.analytical_writing import compose_analysis
                analysis["presentation"] = compose_analysis(task, analysis, context.report_writer,
                    goal=context.writing_goal, reviews=context.writing_reviews)
            else:
                analysis["presentation"] = reading_view(task, analysis)
                analysis.update(ai_status="NOT_RUN", delivery_status="EVIDENCE_REPORT")
            analysis["budget"] = context.budget.snapshot()
            markdown = render_competitive_report(task, analysis)
            result = {"phase": "competitive_analysis", "status": analysis["status"], "run_id": run_id,
                      "analysis_complete": complete, "budget": context.budget.snapshot(), "report_id": None,
                      "research_policy": context.audit_policy(), "report_type": report_type,
                      "ai_status": analysis["ai_status"], "delivery_status": analysis["delivery_status"]}
            with p.transaction() as tx:
                result["report_id"] = p.reports.create(tx, competitor_id=products[0].product_id, run_id=run_id,
                    report_type=report_type, status="GENERATED", generator_version="competitive-report-v3",
                    content_markdown=markdown, summary={"report_type": report_type,
                        "title": analysis["presentation"]["title"], "executive_summary": analysis["presentation"]["executive_summary"],
                        "content_json": analysis, "section_count": len(analysis["presentation"]["sections"]), "change_summary": {}, "warnings": analysis["issues"]})
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

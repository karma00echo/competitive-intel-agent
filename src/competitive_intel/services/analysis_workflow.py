"""Single controlled natural-language workflow using existing research services."""

from dataclasses import asdict
from time import monotonic

from competitive_intel.domain.analysis_task import AnalysisTaskSpec
from competitive_intel.domain.competitive_matrix import ResearchProduct
from competitive_intel.domain.sources import SourceDiscoveryLimits
from competitive_intel.domain.search import SearchIntent
from competitive_intel.domain.task_budget import BudgetExhausted
from .task_understanding_service import TaskUnderstandingService
from .competitor_discovery import CompetitorDiscoveryService


class AnalysisWorkflow:
    def __init__(self, persistence, context):
        self.persistence, self.context = persistence, context

    def prepare(self, text):
        p = self.persistence
        with p.transaction() as tx:
            p.reports.require_competitive_schema(tx)
            rid = p.agent_runs.create(tx, input_name=text[:255], normalized_input=text.casefold()[:255], max_tool_calls=1)
            stage = p.stage_events.create(tx, run_id=rid, stage="SOURCE_DISCOVERY", attempt_no=1, max_attempts=1)
            call = p.tool_calls.create(tx, run_id=rid, stage_event_id=stage, call_index=1,
                                      tool_name="run_competitive_workflow", input_summary={"text": text})
            p.tool_calls.checkpoint(tx, call, output_summary={"phase": "task_understanding", "status": "RUNNING",
                "run_id": rid, "report_id": None, "budget": self.context.budget.snapshot()})
        return rid, stage, call

    def execute(self, text, handles):
        from .agent_runner import AgentRunner
        p, context = self.persistence, self.context
        rid, stage, call = handles
        started = monotonic()
        result = {"run_id": rid, "status": "RUNNING", "phase": "task_understanding", "task": None,
                  "products": [], "issues": [], "report_id": None, "analysis_complete": False,
                  "research_policy": context.audit_policy()}

        def checkpoint(budget=None):
            result["budget"] = budget or context.budget.snapshot()
            result["elapsed_seconds"] = round(monotonic() - started, 3)
            with p.transaction() as tx:
                p.tool_calls.checkpoint(tx, call, output_summary=result)

        context.budget.checkpoint = checkpoint
        try:
            checkpoint()
            interpreted = TaskUnderstandingService(context.understanding_provider()).interpret(text)
            result["interpretation"] = interpreted
            if interpreted["status"] != "READY":
                result["status"] = interpreted["status"]
                result["task"] = interpreted["task"]
                return result
            task = AnalysisTaskSpec.model_validate(interpreted["task"])
            result["task"] = task.model_dump()
            selected = list(task.competitors)
            expected_domains = {}
            if task.discover_competitors:
                result["phase"] = "competitor_discovery"
                checkpoint()
                discovery = CompetitorDiscoveryService(context, context.search_provider(), context.page_fetcher(), context.candidate_evaluator())
                discovery.interpretation_audit = interpreted["audit"]
                found = AgentRunner.discover_competitors(p, task, discovery)
                context.budget.checkpoint = checkpoint
                result["discovery"] = found
                selected = found["selected"]
                if found["status"] in {"FAILED", "NEEDS_CLARIFICATION"}:
                    result["status"] = found["status"]
                    return result
                # Research must not silently bind a discovered name to another domain.
                for candidate in found.get("candidates", []):
                    identity = candidate.get("identity") or {}
                    if identity.get("domain"):
                        expected_domains[candidate["name"]] = identity["domain"]
                if (found.get("target") or {}).get("domain"):
                    expected_domains[task.target] = found["target"]["domain"]
            products = []
            for name in [task.target, *selected]:
                result["phase"], result["current_product"] = "product_research", name
                checkpoint()
                product, audit = self.research(name, expected_domains.get(name))
                products.append(product)
                result["products"].append({**asdict(product), "research": audit})
                checkpoint()
            if not products[0].identity_verified:
                result["status"] = "PARTIAL"
                result["issues"].append("TARGET_IDENTITY_UNVERIFIED_NO_REPORT")
                return result
            result["phase"] = "comparison"
            checkpoint()
            comparison = AgentRunner.compare_products(p, task, products, context)
            result.update(status=comparison["status"], report_id=comparison["report_id"],
                          comparison_run_id=comparison["run_id"], analysis_complete=comparison["analysis_complete"])
            result["comparison"] = comparison
            result["phase"] = "finished"
            return result
        except BudgetExhausted:
            result["status"] = "PARTIAL"
            result["issues"].append("TASK_BUDGET_EXHAUSTED")
            return result
        except Exception as exc:
            result["status"] = "FAILED"
            result["issues"].append("WORKFLOW_" + type(exc).__name__)
            return result
        finally:
            context.budget.checkpoint = None
            result["budget"] = context.budget.snapshot()
            result["elapsed_seconds"] = round(monotonic() - started, 3)
            complete = result["status"] == "COMPLETE"
            failed = result["status"] == "FAILED"
            with p.transaction() as tx:
                p.tool_calls.finish(tx, call, status="FAILED" if failed else "SUCCEEDED", output_summary=result)
                p.stage_events.finish(tx, stage, status="FAILED" if failed else "SUCCEEDED")
                p.agent_runs.finish(tx, rid, status="COMPLETED" if complete else "FAILED" if failed else "PARTIAL_SUCCESS",
                                    current_state="FAILED" if failed else "COMPLETED",
                                    error_code=None if complete else "WORKFLOW_" + result["status"])
            context.close()

    def research(self, name, expected_domain=None):
        p, context = self.persistence, self.context
        cid = run_id = None
        audit = {"sources": [], "issues": [], "fact_count": 0}
        identity = False
        try:
            if context.budget.exhausted:
                raise BudgetExhausted(context.budget.exhausted)
            sources, snapshots, facts = context.research_services(p,
                source_limits=SourceDiscoveryLimits(max_pages=3, max_supplemental_searches=0, max_official_validations=2))
            discovered = sources.discover(name, expected_domain=expected_domain,
                search_intents=(SearchIntent.OFFICIAL_SITE, SearchIntent.FEATURES, SearchIntent.PRICING))
            audit.update(queries=list(discovered.queries), official_domain=discovered.official_domain,
                         source_ids=list(discovered.saved_source_ids))
            audit["discovery"] = asdict(discovered)
            audit["search_requests"] = sources.search_audit
            audit["validation_fetches"] = sources.fetch_audit
            if discovered.errors:
                audit["issues"].append("SOURCE_DISCOVERY_PARTIAL")
            if not discovered.official_domain or not discovered.saved_source_ids:
                audit["issues"].append("IDENTITY_OR_SOURCES_UNVERIFIED")
            elif expected_domain and discovered.official_domain != expected_domain:
                audit["issues"].append("DISCOVERY_RESEARCH_IDENTITY_MISMATCH")
            else:
                identity = True
            if identity:
                with p.transaction() as tx:
                    profile = p.competitors.get_by_normalized_name(tx, discovered.identity.normalized_name)
                    cid = profile["id"]
                    run_id = p.agent_runs.create(tx, competitor_id=cid, input_name=name,
                        normalized_input=discovered.identity.normalized_name, run_mode="UNKNOWN", current_state="PAGE_FETCHING")
                for sid in discovered.saved_source_ids:
                    snapshots.process(source_id=sid, run_id=run_id)
                    with p.transaction() as tx:
                        source = p.sources.get(tx, sid)
                        snapshot = p.snapshots.get_successful_for_source_run(tx, sid, run_id)
                    audit["sources"].append({"source_id": sid, "url": source["url"], "snapshot_id": snapshot["id"] if snapshot else None})
                    if not snapshot:
                        audit["issues"].append("PAGE_FETCH_FAILED")
                extracted = facts.extract(name, run_id=run_id, current_run_only=True)
                audit["extraction"] = {"candidate_count": extracted.candidate_count,
                    "provider_calls": list(extracted.provider_calls),
                    "warnings": list(extracted.warnings), "errors": list(extracted.errors),
                    "rejected": [{"status": item.status.value, "reason": item.reason}
                                 for item in extracted.rejected]}
                audit["fact_count"] = len(extracted.saved)
                if extracted.errors or any(item.status.value != "DUPLICATE" for item in extracted.rejected):
                    audit["issues"].append("FACT_EXTRACTION_PARTIAL")
        except BudgetExhausted:
            audit["issues"].append("TASK_BUDGET_EXHAUSTED")
        except Exception as exc:
            audit["issues"].append("RESEARCH_" + type(exc).__name__)
        if run_id:
            with p.transaction() as tx:
                audit["fact_count"] = len(p.fact_observations.list_for_run(tx, run_id))
                if not audit["fact_count"]:
                    audit["issues"].append("NO_CONFIRMED_FACTS")
                p.agent_runs.finish(tx, run_id, status="PARTIAL_SUCCESS" if audit["issues"] else "COMPLETED", current_state="COMPLETED")
        return ResearchProduct(name, cid, run_id, identity,
            "PARTIAL" if audit["issues"] else "COMPLETE", tuple(audit["issues"])), audit

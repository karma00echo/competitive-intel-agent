"""Atomic partial evidence publication. Never calls comparison or activation."""
import json
from dataclasses import asdict

from competitive_intel.domain.agent import AgentRunSummary, AgentState
from competitive_intel.domain.evidence import normalized_evidence
from competitive_intel.persistence import Persistence


def needs_partial(data: dict, fetch: dict) -> bool:
    return bool(
        data.get("errors") or fetch.get("failure_count")
        or any(p.get("page_status") not in {"SUCCEEDED"}
               for p in data.get("provider_calls", []))
        or any(r.get("status") != "DUPLICATE" for r in data.get("rejected", []))
    )


class PartialResultService:
    def __init__(self, persistence: Persistence):
        self.p = persistence

    def complete(self, context, stage_id: int, data: dict, fetch: dict):
        """Report, critical audit and terminal status commit together or not at all."""
        pages = data.get("provider_calls", [])
        conflicts = [c for p in pages for c in p.get("identity_conflicts", [])]
        conflicts += [r for p in pages for r in p.get("fact_rejections", [])
                      if r.get("error_code") == "CONFLICTING_FACT_IDENTITY"]
        conflict_keys = {c.get("canonical_identity") for c in conflicts}
        # An unidentified conflict cannot safely be excluded from the evidence set.
        if None in conflict_keys:
            raise ValueError("UNIDENTIFIED_CONFLICT")
        if any("CONFLICT" in str(e) for e in data.get("errors", [])) and not conflicts:
            raise ValueError("MISSING_CONFLICT_AUDIT")
        with self.p.transaction() as tx:
            run = self.p.agent_runs.get(tx, context.run_id)
            sources = self.p.sources.list_verified(tx, context.competitor_id)
            snapshots = self.p.snapshots.list_for_run(tx, context.run_id)
            facts = self.p.fact_observations.list_for_run(tx, context.run_id)
            calls = self.p.tool_calls.list_for_run(tx, context.run_id)
            if (not run or run["status"] != "RUNNING"
                    or run["competitor_id"] != context.competitor_id
                    or self.p.changes.list_for_run(tx, context.run_id)):
                raise ValueError("INVALID_PARTIAL_RUN")
            if not any(c["tool_name"] == "extract_competitor_facts"
                       and c.get("output_summary") for c in calls):
                raise ValueError("MISSING_EXTRACTION_AUDIT")
            by_source = {s["id"]: s for s in sources}
            by_snapshot = {s["id"]: s for s in snapshots}
            visible = []
            for f in facts:
                snap = by_snapshot.get(f["observed_snapshot_id"])
                source = by_source.get(f["source_id"])
                if (f["comparison_status"] != "PENDING"
                        or f["evidence_status"] != "CONFIRMED"
                        or f["competitor_id"] != context.competitor_id
                        or not snap or not source
                        or snap["source_id"] != source["id"]
                        or snap["fetch_status"] != "SUCCESS"
                        or not f["observed_at"]
                        or not f["observed_evidence"]
                        or normalized_evidence(f["observed_evidence"]) not in
                        normalized_evidence(snap["clean_content"] or "")):
                    raise ValueError("INVALID_PARTIAL_PROVENANCE")
                if f["fact_key"] in conflict_keys:
                    continue
                visible.append({
                    "fact_id": f["id"], "fact_key": f["fact_key"],
                    "category": f["fact_category"],
                    "value": json.loads(f["fact_value"]) if isinstance(f["fact_value"], str) else f["fact_value"],
                    "source_id": source["id"], "source_url": source["url"],
                    "snapshot_id": snap["id"], "evidence": f["observed_evidence"],
                    "confidence": float(f["observed_confidence"]),
                    "observation_status": "PENDING",
                })
            if not visible:
                raise ValueError("NO_UNCONTESTED_VERIFIED_FACTS")
            coverage = []
            for source in sources:
                page = next((p for p in pages if p.get("source_id") == source["id"]), {})
                snaps = [s for s in snapshots if s["source_id"] == source["id"]]
                coverage.append({
                    "source_id": source["id"], "url": source["url"],
                    "snapshot_ids": [s["id"] for s in snaps],
                    "fetch_status": [s["fetch_status"] for s in snaps],
                    "page_status": page.get("page_status", "NOT_EXTRACTED"),
                    "rejected_count": page.get("rejected_count", 0),
                })
            failed = sum(c["page_status"] not in {"SUCCEEDED", "NO_FACTS"} for c in coverage)
            note = ("PARTIAL_SUCCESS — partial evidence only. All observations remain PENDING. "
                    "No baseline activation, comparison, Changes or Signals. Missing or empty "
                    "sources are unknown, never proof of removal. Conflicting identities excluded.")
            sections = [
                {"heading": "Partial result limitations", "items": [note]},
                {"heading": "Source coverage", "items": coverage},
                {"heading": "Verified, uncontested evidence (PENDING)", "items": visible},
                {"heading": "Rejected facts / missing information", "items": data.get("rejected", [])},
                {"heading": "Field diagnostics", "items": [d for p in pages for d in p.get("evidence_diagnostics", [])]},
                {"heading": "Unresolved identities (not conclusions)", "items": conflicts},
                {"heading": "Errors and gaps", "items": data.get("errors", []) + data.get("warnings", [])},
            ]
            content = {"title": f"Partial Evidence Report — {context.competitor_name}",
                "executive_summary": note, "sections": sections, "change_summary": {},
                "report_type": "PARTIAL_EVIDENCE", "run_id": context.run_id,
                "baseline_eligible": False, "failed_source_count": failed,
                "visible_fact_ids": [f["fact_id"] for f in visible],
                "excluded_conflict_keys": sorted(conflict_keys)}
            # Generic deterministic renderer preserves *all* coverage/diagnostic fields.
            markdown = "# " + content["title"] + "\n\n" + note + "\n"
            for section in sections:
                markdown += "\n## " + section["heading"] + "\n\n"
                markdown += "\n".join("- " + json.dumps(i, ensure_ascii=False, default=str)
                                      for i in section["items"]) + "\n"
            report_id = self.p.reports.create(tx, competitor_id=context.competitor_id,
                run_id=context.run_id, report_type="PARTIAL_EVIDENCE", status="GENERATED",
                generator_version="partial-evidence-v1", content_markdown=markdown,
                summary={"report_type": "PARTIAL_EVIDENCE", "title": content["title"],
                    "executive_summary": note, "content_json": content,
                    "section_count": len(sections), "change_summary": {}, "warnings": [note]})
            metadata = context.tool_results["get_competitor_profile"].data
            summary = AgentRunSummary(
                run_id=context.run_id, competitor_name=context.competitor_name,
                normalized_name=context.normalized_name, run_mode=context.run_mode,
                final_state=AgentState.PARTIAL_SUCCESS, official_homepage=None,
                verified_source_count=len(sources),
                page_fetch_success_count=fetch.get("success_count", 0),
                page_fetch_failure_count=fetch.get("failure_count", 0),
                baseline_page_count=0, unchanged_page_count=0, changed_page_count=0,
                confirmed_fact_count=len(visible), rejected_fact_count=data.get("rejected_count", 0),
                duplicate_fact_count=data.get("duplicate_count", 0),
                tool_call_count=context.tool_call_count + 1,
                warnings=(note,), errors=tuple(data.get("errors", [])),
                report_id=report_id, report_type="PARTIAL_EVIDENCE",
                search_provider=metadata.get("search_provider", "fixture"),
                fetch_mode=metadata.get("fetch_mode", "fixture"),
                fact_provider=metadata.get("fact_provider", "fixture"),
                fact_extraction_status="PARTIAL_SUCCESS")
            audit = self.p.tool_calls.create(tx, run_id=context.run_id,
                stage_event_id=stage_id, call_index=context.tool_call_count + 1,
                tool_name="finalize_run_summary", input_summary={"partial": True})
            self.p.tool_calls.finish(tx, audit, status="SUCCEEDED",
                output_summary={"summary": asdict(summary), "partial_evidence": {
                    "report_id": report_id, "failed_source_count": failed,
                    "visible_fact_ids": content["visible_fact_ids"],
                    "excluded_conflict_keys": sorted(conflict_keys),
                    "coverage": coverage}, "baseline_integrity": {
                        "version": 1, "run_kind": "FULL_AGENT_RUNNER", "eligible": False}})
            self.p.stage_events.finish(tx, stage_id, status="FAILED",
                error_code="PARTIAL_EXTRACTION", error_message=note)
            self.p.agent_runs.finish(tx, context.run_id, status="PARTIAL_SUCCESS",
                                     current_state="COMPLETED")
        return summary

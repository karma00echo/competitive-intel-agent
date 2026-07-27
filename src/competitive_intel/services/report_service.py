"""Deterministic JSON and readable Markdown competitor reports."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from competitive_intel.domain.agent import RunMode
from competitive_intel.persistence import Persistence


REPORT_GENERATOR = "deterministic-report-v1"
REPORT_PROMPT_VERSION = "none-deterministic-v1"


def _decode(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


@dataclass(frozen=True, slots=True)
class GeneratedReport:
    report_id: int
    report_type: str
    title: str
    executive_summary: str
    content_json: dict[str, Any]
    content_markdown: str
    section_count: int
    change_summary: dict[str, int]
    warnings: tuple[str, ...] = ()


class CompetitorReportService:
    def __init__(self, persistence: Persistence) -> None:
        self._persistence = persistence

    def generate(
        self,
        competitor_id: int,
        run_id: int,
        run_mode: RunMode,
    ) -> GeneratedReport:
        with self._persistence.transaction() as session:
            existing = self._persistence.reports.get_for_run(
                session,
                run_id,
                "BASELINE" if run_mode == RunMode.BASELINE else "CHANGE_TRACKING",
            )
            competitor = self._persistence.competitors.get(
                session, competitor_id
            )
            run = self._persistence.agent_runs.get(session, run_id)
            sources = self._persistence.sources.list_verified(
                session, competitor_id
            )
            facts = self._persistence.fact_observations.list_for_run(
                session, run_id
            )
            changes = self._persistence.changes.list_for_run(session, run_id)
            snapshots = self._persistence.snapshots.list_for_run(session, run_id)
            previous = (
                self._persistence.agent_runs.get_previous_successful_with_facts(
                    session, competitor_id, run_id
                )
                if run_mode == RunMode.REFRESH else None
            )
        if competitor is None or run is None:
            raise ValueError("Competitor or run does not exist.")
        if existing:
            summary = _decode(existing["summary_json"]) or {}
            return self._from_record(existing, summary)
        now = datetime.now(UTC).replace(tzinfo=None)
        warnings = [
            f"Source {item['source_id']} was not successfully fetched."
            for item in snapshots
            if item["fetch_status"] != "SUCCESS"
        ]
        if run_mode == RunMode.BASELINE:
            content = self._baseline_content(
                competitor, run, sources, facts, now, warnings
            )
            physical_type = "BASELINE"
            report_type = "BASELINE_REPORT"
        else:
            content = self._change_content(
                competitor, run, previous, sources, changes, facts, now, warnings
            )
            physical_type = "CHANGE_TRACKING"
            report_type = "CHANGE_TRACKING_REPORT"
        markdown = self._markdown(content)
        summary = {
            "report_type": report_type,
            "title": content["title"],
            "executive_summary": content["executive_summary"],
            "content_json": content,
            "section_count": len(content["sections"]),
            "change_summary": content["change_summary"],
            "warnings": warnings,
            "prompt_version": REPORT_PROMPT_VERSION,
            "generator": REPORT_GENERATOR,
        }
        with self._persistence.transaction() as session:
            report_id = self._persistence.reports.create(
                session,
                competitor_id=competitor_id,
                run_id=run_id,
                report_type=physical_type,
                status="GENERATED",
                generator_version=REPORT_GENERATOR,
                content_markdown=markdown,
                summary=summary,
            )
        return GeneratedReport(
            report_id,
            report_type,
            content["title"],
            content["executive_summary"],
            content,
            markdown,
            len(content["sections"]),
            content["change_summary"],
            tuple(warnings),
        )

    def get(
        self,
        *,
        report_id: int | None = None,
        run_id: int | None = None,
        competitor_name: str | None = None,
        latest: bool = False,
    ) -> GeneratedReport | None:
        with self._persistence.transaction() as session:
            record = None
            if report_id is not None:
                record = self._persistence.reports.get(session, report_id)
            elif run_id is not None:
                for report_type in ("CHANGE_TRACKING", "BASELINE"):
                    record = self._persistence.reports.get_for_run(
                        session, run_id, report_type
                    )
                    if record:
                        break
            elif competitor_name and latest:
                competitor = self._persistence.competitors.get_by_normalized_name(
                    session, competitor_name.strip().casefold()
                )
                if competitor:
                    record = self._persistence.reports.get_latest_for_competitor(
                        session, competitor["id"]
                    )
        if not record:
            return None
        return self._from_record(record, _decode(record["summary_json"]) or {})

    @staticmethod
    def _baseline_content(
        competitor, run, sources, facts, generated_at, warnings
    ) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for fact in facts:
            grouped.setdefault(fact["fact_category"], []).append(
                {
                    "fact_key": fact["fact_key"],
                    "value": _decode(fact["normalized_value"]),
                    "source_url": fact["observed_source_url"],
                    "evidence": fact["observed_evidence"],
                    "confidence": float(fact["observed_confidence"]),
                }
            )
        homepage = next(
            (item["url"] for item in sources if item["source_type"] == "HOMEPAGE"),
            None,
        )
        sections = [
            {"heading": "Official sources", "items": [
                {"type": item["source_type"], "url": item["url"]}
                for item in sources
            ]},
            {"heading": "Positioning", "items": grouped.get("POSITIONING", [])},
            {"heading": "Core features", "items": grouped.get("FEATURE", [])},
            {"heading": "Plans", "items": grouped.get("PLAN", [])},
            {"heading": "Prices", "items": grouped.get("PRICE", [])},
            {"heading": "Product updates", "items": grouped.get("PRODUCT_UPDATE", [])},
            {"heading": "Evidence coverage", "items": {
                "confirmed_fact_count": len(facts),
                "verified_source_count": len(sources),
            }},
            {"heading": "Data limitations", "items": warnings},
            {"heading": "Run summary", "items": {
                "run_id": run["id"], "run_mode": "BASELINE"
            }},
        ]
        return {
            "report_type": "BASELINE_REPORT",
            "title": f"{competitor['canonical_name']} competitive baseline",
            "competitor_name": competitor["canonical_name"],
            "analysis_time": generated_at.isoformat(),
            "official_homepage": homepage,
            "executive_summary": (
                f"Established a baseline with {len(facts)} confirmed facts "
                f"from {len(sources)} verified official sources."
            ),
            "change_summary": {
                "added_count": 0, "removed_count": 0, "modified_count": 0,
                "unchanged_count": 0, "uncomparable_count": 0,
            },
            "sections": sections,
        }

    @staticmethod
    def _change_content(
        competitor, run, previous_run, sources, changes, facts, generated_at, warnings
    ) -> dict[str, Any]:
        logical = [
            {
                "change_type": (
                    "UNCOMPARABLE"
                    if item["change_type"] == "UNKNOWN"
                    else item["change_type"]
                ),
                "fact_key": item["fact_key"],
                "old_fact_id": item["old_fact_id"],
                "new_fact_id": item["new_fact_id"],
                "old_value": _decode(item["old_value"]),
                "new_value": _decode(item["new_value"]),
                "evidence": item["evidence_text"],
                "reason": item["impact_assessment"],
                "confidence": (
                    float(item["confidence"])
                    if item["confidence"] is not None else None
                ),
            }
            for item in changes
        ]
        counts = {
            f"{kind.casefold()}_count": sum(
                item["change_type"] == kind for item in logical
            )
            for kind in (
                "ADDED", "REMOVED", "MODIFIED", "UNCHANGED", "UNCOMPARABLE"
            )
        }
        categorized = {
            kind: [item for item in logical if item["change_type"] == kind]
            for kind in (
                "ADDED", "REMOVED", "MODIFIED", "UNCOMPARABLE"
            )
        }
        inferences = CompetitorReportService._inferences(logical)
        sections = [
            {"heading": "Added facts", "items": categorized["ADDED"]},
            {"heading": "Removed facts", "items": categorized["REMOVED"]},
            {"heading": "Modified facts", "items": categorized["MODIFIED"]},
            {"heading": "Unchanged facts", "items": counts["unchanged_count"]},
            {"heading": "Uncomparable facts", "items": categorized["UNCOMPARABLE"]},
            {"heading": "Price changes", "items": [
                item for item in logical
                if item["fact_key"].startswith("price.")
                and item["change_type"] != "UNCHANGED"
            ]},
            {"heading": "Plan changes", "items": [
                item for item in logical
                if item["fact_key"].startswith("plan.")
                and item["change_type"] != "UNCHANGED"
            ]},
            {"heading": "Feature changes", "items": [
                item for item in logical
                if item["fact_key"].startswith("feature.")
                and item["change_type"] != "UNCHANGED"
            ]},
            {"heading": "Positioning changes", "items": [
                item for item in logical
                if item["fact_key"].startswith("positioning.")
                and item["change_type"] != "UNCHANGED"
            ]},
            {"heading": "Product updates", "items": [
                item for item in logical
                if item["fact_key"].startswith("product_update.")
                and item["change_type"] != "UNCHANGED"
            ]},
            {
                "heading": "Possible impacts (analytical inferences)",
                "items": inferences,
            },
            {"heading": "Evidence and sources", "items": [
                {"type": item["source_type"], "url": item["url"]}
                for item in sources
            ]},
            {"heading": "Risk notes", "items": warnings},
            {"heading": "Run summary", "items": {
                "run_id": run["id"], "run_mode": "REFRESH",
                "previous_run_id": (
                    previous_run["id"] if previous_run else None
                ),
                "fact_count": len(facts),
            }},
        ]
        return {
            "report_type": "CHANGE_TRACKING_REPORT",
            "title": f"{competitor['canonical_name']} change tracking report",
            "competitor_name": competitor["canonical_name"],
            "analysis_time": generated_at.isoformat(),
            "current_run_id": run["id"],
            "previous_run_id": previous_run["id"] if previous_run else None,
            "executive_summary": (
                f"Detected {counts['added_count']} added, "
                f"{counts['removed_count']} removed and "
                f"{counts['modified_count']} modified facts; "
                f"{counts['unchanged_count']} were unchanged."
            ),
            "change_summary": counts,
            "sections": sections,
        }

    @staticmethod
    def _inferences(changes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for change in changes:
            if change["change_type"] in {"UNCHANGED", "UNCOMPARABLE"}:
                continue
            key = change["fact_key"]
            if key.startswith("price."):
                text = (
                    "Public price terms changed; actual customer cost impact "
                    "depends on plan and usage."
                )
            elif key.startswith("plan."):
                text = (
                    "Public packaging changed; entitlement impact requires "
                    "checking the affected plan."
                )
            elif key.startswith("feature."):
                text = (
                    "Public capability availability changed; workflow impact "
                    "depends on whether users rely on this feature."
                )
            elif key.startswith("positioning."):
                text = (
                    "Public positioning changed; this may indicate a shift in "
                    "target audience or use-case emphasis."
                )
            else:
                text = (
                    "A public product fact changed; downstream impact requires "
                    "product-specific verification."
                )
            items.append(
                {
                    "analysis_type": "INFERENCE",
                    "trigger_fact_key": key,
                    "trigger_change_type": change["change_type"],
                    "text": text,
                }
            )
        return items

    @staticmethod
    def _markdown(content: dict[str, Any]) -> str:
        lines = [
            f"# {content['title']}",
            "",
            content["executive_summary"],
            "",
            f"- Competitor: {content['competitor_name']}",
            f"- Analysis time: {content['analysis_time']}",
            "",
        ]
        for section in content["sections"]:
            lines.extend([f"## {section['heading']}", ""])
            items = section["items"]
            if isinstance(items, list):
                if not items:
                    lines.append("- None")
                for item in items:
                    if isinstance(item, dict):
                        lines.extend(
                            CompetitorReportService._markdown_item(item)
                        )
                    else:
                        lines.append(f"- {item}")
            elif isinstance(items, dict):
                for key, value in items.items():
                    lines.append(f"- {key}: {value}")
            else:
                lines.append(str(items))
            lines.append("")
        return "\n".join(lines).rstrip() + "\n"

    @staticmethod
    def _markdown_item(item: dict[str, Any]) -> list[str]:
        label = (
            item.get("fact_key")
            or item.get("url")
            or item.get("change_type")
            or "Item"
        )
        if "change_type" in item:
            old = json.dumps(
                item.get("old_value"), ensure_ascii=False, sort_keys=True
            )
            new = json.dumps(
                item.get("new_value"), ensure_ascii=False, sort_keys=True
            )
            return [
                f"- **{label}** — {item['change_type']}",
                f"  - Old: {old}",
                f"  - New: {new}",
                f"  - Reason: {item.get('reason') or 'Not provided'}",
            ]
        if "value" in item:
            value = json.dumps(
                item["value"], ensure_ascii=False, sort_keys=True
            )
            return [
                f"- **{label}**: {value}",
                f"  - Evidence: {item.get('evidence')}",
                f"  - Source: {item.get('source_url')}",
            ]
        if "url" in item:
            return [f"- {item.get('type', 'Source')}: {item['url']}"]
        if item.get("analysis_type") == "INFERENCE":
            return [
                f"- **INFERENCE — {item['trigger_fact_key']}**: {item['text']}",
                f"  - Trigger: {item['trigger_change_type']}",
            ]
        return [f"- **{label}**"]

    @staticmethod
    def _from_record(record, summary: dict[str, Any]) -> GeneratedReport:
        content = summary.get("content_json") or {}
        return GeneratedReport(
            int(record["id"]),
            summary.get("report_type", str(record["report_type"])),
            summary.get("title", ""),
            summary.get("executive_summary", ""),
            content,
            record["content_markdown"] or "",
            int(summary.get("section_count", 0)),
            dict(summary.get("change_summary", {})),
            tuple(summary.get("warnings", [])),
        )

"""Reuse repository observations; never research, extract or overwrite a report."""
import json
from pathlib import Path

from competitive_intel.domain.analysis_task import AnalysisTaskSpec
from competitive_intel.domain.competitive_matrix import ResearchProduct, decode
from competitive_intel.domain.analytical_writing import digest


def saved_scope(persistence, report_id):
    with persistence.transaction() as tx:
        report = persistence.reports.get(tx, report_id)
        if not report or report["report_type"] not in {"COMPETITIVE_ANALYSIS", "COMPETITIVE_ANALYSIS_PARTIAL"}:
            raise ValueError("COMPETITIVE_REPORT_REQUIRED")
        calls = persistence.tool_calls.list_for_run(tx, report["run_id"])
    call = next((c for c in calls if c["tool_name"] == "compare_products"), None)
    if not call:
        raise ValueError("TRUSTED_RESEARCH_SCOPE_REQUIRED")
    scope = decode(call["input_summary"])
    task = AnalysisTaskSpec.model_validate(scope["task"])
    # Explicit existing-evidence comparison does not repeat competitor discovery.
    products = [ResearchProduct(**p) for p in scope["products"]]
    task = task.model_copy(update={"discover_competitors": False,
                                  "competitors": [p.name for p in products[1:]]})
    return task, products


class PinnedFixtureWriter:
    """Operator-selected fixture; immutable evidence+request hash prevents reuse drift."""
    origin = "fixture"
    usage = None

    def __init__(self, path):
        self.artifact = json.loads(Path(path).read_text(encoding="utf-8"))
        self.reviews = self.artifact.get("reviews", {})

    def write(self, request):
        if digest(request) != self.artifact["packet_hash"]:
            raise ValueError("FIXTURE_SCOPE_MISMATCH")
        return self.artifact["payload"]


class StoredCandidateWriter:
    """Publish independently reviewed saved prose with zero new provider calls."""
    usage = None

    def __init__(self, persistence, report_id, *, revision=None):
        with persistence.transaction() as tx:
            row = persistence.reports.get(tx, report_id)
        analysis = decode(row["summary_json"])["content_json"]
        self.audit = analysis["presentation"]["writing"]["analytical"]
        self.origin = "fixture" if self.audit["origin"] == "fixture" else "model_replay"
        self.revision = None
        if revision is not None:
            # Server-owned editorial copy; never mutate the historical candidate.
            if (revision.get("source_report_id") != report_id
                    or revision.get("source_candidate_hash") != digest(self.audit["candidate"])
                    or revision.get("packet_hash") != self.audit["packet_hash"]
                    or not revision.get("changes") or not revision.get("reviewer")):
                raise ValueError("REVIEWED_REVISION_MISMATCH")
            self.revision = revision

    def write(self, request):
        if digest(request) != self.audit["packet_hash"]:
            raise ValueError("REVIEWED_EVIDENCE_CHANGED")
        return self.revision["payload"] if self.revision else self.audit["candidate"]

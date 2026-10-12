"""Explicit paid smoke only. Never imported or launched by ordinary pytest."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from competitive_intel.api.schemas import AnalysisRequest
from competitive_intel.config import Settings
from competitive_intel.persistence import Database, Persistence
from competitive_intel.web.runtime import build_runner


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-paid", action="store_true", help="Required consent to paid API calls and application DB writes")
    parser.add_argument("--competitor", default="Notion")
    parser.add_argument("--runs", type=int, choices=(1, 2), default=2)
    parser.add_argument("--max-calls-per-run", type=int, choices=range(1, 9), default=4)
    args = parser.parse_args()
    if not args.allow_paid:
        parser.error("Explicit --allow-paid is required; no network requests were made.")
    settings = Settings.from_env()
    if not all((settings.search.api_key, settings.llm.api_key, settings.llm.model, settings.llm.endpoint)):
        print("NOT_RUN: configure SEARCH_API_KEY and LLM_API_KEY / LLM_MODEL / LLM_ENDPOINT locally.")
        return 2
    settings = replace(settings, llm=replace(settings.llm, max_calls=args.max_calls_per_run, max_retries=0))
    database = Database(settings.database)
    persistence = Persistence(database)
    request = AnalysisRequest(competitor_name=args.competitor, search_provider="serper", fact_provider="openai_compatible")
    try:
        for _ in range(args.runs):
            result = build_runner(settings, persistence, request, lambda event: None).run(args.competitor)
            summary = result.summary
            print(json.dumps({"run_id":result.run_id,"state":result.final_state.value,
                "report_id":summary.report_id if summary else None,
                "facts":summary.confirmed_fact_count if summary else 0,
                "modified":summary.modified_count if summary else None,
                "audit_url":f"http://127.0.0.1:8000/developer/runs/{result.run_id}"}))
            if not summary or not summary.confirmed_fact_count or result.final_state.value == "FAILED":
                print("STOPPED: inspect the persisted audit; no fixture fallback and no additional competitor.")
                return 1
    finally:
        database.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

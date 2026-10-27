"""Generate NEW local artifacts from a trusted persisted analysis export.

No database access, HTTP, provider construction or historical writes. Do not use
untrusted client JSON in place of repository-built matrices. Output is local-only.
"""
import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from competitive_intel.domain.analysis_task import AnalysisTaskSpec
from competitive_intel.domain.comparison_presentation import reading_view
from competitive_intel.services.competitive_report_service import render_competitive_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Trusted persisted analysis JSON export")
    parser.add_argument("output", type=Path, help="New local directory; must not exist")
    args = parser.parse_args()
    original = args.input.read_bytes()
    analysis = json.loads(original)
    original_matrix = deepcopy(analysis["matrix"])
    args.output.mkdir(parents=True, exist_ok=False)
    for language in ("zh-CN", "en"):
        task = AnalysisTaskSpec.model_validate(analysis["task"]).model_copy(update={"output_language": language})
        rendered = deepcopy(analysis)
        rendered["presentation"] = reading_view(task, rendered)
        view = rendered["presentation"]
        (args.output / f"reading.{language}.json").write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
        note = ("离线写作样例：沿用历史确认事实；未启动新研究或调用模型，历史报告未修改。\n\n" if language == "zh-CN" else "Offline writing sample using historical confirmed facts. No new research, model calls or historical updates.\n\n")
        (args.output / f"report.{language}.md").write_text(note + render_competitive_report(task, rendered), encoding="utf-8")
    assert analysis["matrix"] == original_matrix and args.input.read_bytes() == original
    (args.output / "verification.json").write_text(json.dumps(dict(
        input_sha256=sha256(original).hexdigest(), facts=len(original_matrix["facts"]),
        evidence=len(original_matrix["evidence"]), matrix_unchanged=True,
        history_written=False, provider_calls=0, status=analysis["status"]), indent=2), encoding="utf-8")
    print("Offline artifacts created; source input unchanged.")


if __name__ == "__main__":
    main()

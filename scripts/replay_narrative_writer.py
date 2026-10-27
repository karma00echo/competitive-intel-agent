"""Offline-only Narrative Writer replay. This command has NO live mode."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from competitive_intel.config import Settings
from competitive_intel.domain.analysis_task import AnalysisTaskSpec
from competitive_intel.domain.narrative import prepare_narrative, variants, write_narrative
from competitive_intel.infrastructure.agent.narrative_writer import isolated_budget, reviewed_rates
from competitive_intel.services.research_context import ResearchContext
from competitive_intel.services.competitive_report_service import render_competitive_report


class MockResponse:
    status_code = 200
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size): yield self.body


class MockSession:
    calls = 0
    def post(self, url, **kwargs):
        self.calls += 1
        req = json.loads(kwargs["json"]["messages"][1]["content"])
        sections = []
        for section, ids in req["sections"].items():
            ps = []
            for cid in ids:
                _, text, eids = req["claims"][cid]
                options = variants(text)
                ps.append(dict(claim_ids=[cid], variant_ids=[len(options)-1], evidence_ids=sorted(eids), text=options[-1]))
            sections.append(dict(id=section, paragraphs=ps))
        content = dict(document_hash=req["document_hash"], sections=sections)
        return MockResponse(json.dumps(dict(model="deepseek-flash", choices=[dict(finish_reason="stop",
            message=dict(content=json.dumps(content,ensure_ascii=False)))], usage=None), ensure_ascii=False).encode())
    def close(self): pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    source = args.input.read_bytes()
    analysis = json.loads(source)
    task = AnalysisTaskSpec.model_validate(analysis["task"]).model_copy(update={"output_language": "zh-CN"})
    settings = Settings.from_env()
    # The local real model/endpoint is preflighted, but its key is never used.
    settings = replace(settings, llm=replace(settings.llm, api_key="offline-fixture-key"))
    args.output.mkdir(parents=True, exist_ok=False)
    transport = MockSession()
    context = ResearchContext(settings, allow_paid=True, budget=isolated_budget(), rates=reviewed_rates(), session_factory=lambda _: transport)
    try:
        provider = context.narrative_provider(attempt_file=args.output/"mock-attempt.json")
        _, _, request = prepare_narrative(task, analysis)
        provider.preflight(request)
        view = write_narrative(task, analysis, provider)
        if view["writing"]["narrative"]["status"] != "VALIDATED_FINITE_PARAPHRASE":
            raise ValueError("MOCK_REPLAY_FAILED")
        for name, data in (("request.json",request), ("validated-view.json",view),
            ("audit.json",dict(mode="MOCK_ONLY",live_calls=0,mock_calls=transport.calls,
                               provider_usage=None,actual_reserved_usd=0,mock_ledger=context.budget.snapshot(),preflight=provider.audit))):
            (args.output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")
        (args.output/"mock-raw-response.json").write_text(provider.raw_output,encoding="utf-8")
        rendered = {**analysis, "presentation":view}
        (args.output/"report.zh-CN.md").write_text("隔离 Mock 写作样例；未调用真实模型，不能视为模型语言质量验收。\n\n"+render_competitive_report(task,rendered),encoding="utf-8")
        assert args.input.read_bytes()==source
        print("MOCK_ONLY: validated report saved; live calls=0; source unchanged")
    finally:
        context.close()


if __name__ == "__main__":
    main()

from copy import deepcopy
from types import SimpleNamespace
import json
from pathlib import Path
import pytest

from competitive_intel.domain.analysis_task import AnalysisTaskSpec
from competitive_intel.domain.analytical_writing import writing_packet, validate_document, compose_analysis, digest
from tests.discovery_support import spec
from test_report_writing import sample


from tests.analytical_support import fixture_payload, reviewed


def test_open_prose_needs_independent_review_and_server_builds_citations():
    task = spec().model_copy(update={"output_language": "zh-CN"})
    a = sample(); packet = writing_packet(task, a); payload = fixture_payload(packet)
    assert not validate_document(payload, packet)[0]
    reviews = reviewed(payload, packet)
    writer = SimpleNamespace(write=lambda _: payload, origin="fixture")
    view = compose_analysis(task, a, writer, reviews=reviews)
    assert a["delivery_status"] == "DEMO_READY" and a["ai_status"] == "FIXTURE_VALIDATED"
    assert "Fixture" in str(view["sections"]) and "策略建议" in str(view["sections"])
    assert "[1]" in str(view["sections"])
    assert a["status"] == "PARTIAL"
    changed = deepcopy(payload); changed["units"][0]["text"] += "另外支持未经证实的离线同步。"
    accepted, diags = validate_document(changed, packet, reviews)
    assert len(accepted) == 3 and diags[0]["code"] == "SEMANTIC_REVIEW_REQUIRED"
    changed_packet = deepcopy(packet); next(iter(changed_packet["evidence"].values()))["quote"] += " changed"
    assert not validate_document(payload, changed_packet, reviews)[0]


@pytest.mark.parametrize("mutation,code", [
    (lambda u:u.update(fact_ids=["unknown"]), "FACT_UNSUPPORTED"),
    (lambda u:u.update(finding_ids=["unknown"]), "FINDING_UNKNOWN"),
    (lambda u:u.update(text="产品每月只需 $9 即可使用所有功能。"), "NUMERIC_OR_EXTERNAL_ASSERTION"),
    (lambda u:u.update(text="产品明显优于对手，拥有领先的技术优势。"), "UNSUPPORTED_RANKING"),
    (lambda u:u.update(premise=""), "PREMISE_REQUIRED"),
    (lambda u:u.update(verification="", kind="recommendation", section="recommendations"), "VERIFICATION_REQUIRED"),
])
def test_rejections(mutation, code):
    packet = writing_packet(spec(), sample()); payload = fixture_payload(packet)
    mutation(payload["units"][0]); _, diagnostics = validate_document(payload, packet)
    assert diagnostics[0]["code"] == code


def test_format_failure_is_distinct_and_provider_failure_safe():
    task = spec(); a = sample(); packet = writing_packet(task, a)
    assert validate_document({"units": "wrong"}, packet)[1][0]["stage"] == "format"
    def fail(_): raise TimeoutError("private provider message")
    view = compose_analysis(task, a, SimpleNamespace(write=fail))
    assert a["ai_status"] == "FAILED" and "private provider" not in str(view)


def test_historical_run38_packet_keeps_all_facts_and_evidence():
    path = Path("build/run38-quality/original.json")
    if not path.exists(): pytest.skip("Private historical fixture unavailable")
    a = json.loads(path.read_text(encoding="utf-8")); task = AnalysisTaskSpec.model_validate(a["task"])
    packet = writing_packet(task, a)
    assert len(packet["facts"]) == len(packet["evidence"]) == 17
    from competitive_intel.infrastructure.agent.analytical_writer import AnalyticalWriter
    from competitive_intel.infrastructure.agent.narrative_writer import isolated_budget, reviewed_rates
    from competitive_intel.infrastructure.budgeted_transport import BudgetedSession
    from competitive_intel.config import LLMSettings
    from datetime import date
    writer = AnalyticalWriter(LLMSettings(model="deepseek-flash", endpoint="https://api.deepseek.com"),
        BudgetedSession(isolated_budget(), "synthesis", rates=reviewed_rates()))
    writer.preflight(packet, today=date(2026,10,27))
    assert writer.audit["input_token_upper_bound"] <= 16000


@pytest.mark.parametrize("mode", ["ok", "json", "timeout", "length", "http", "oversize"])
def test_real_writer_adapter_offline_and_one_attempt(tmp_path, monkeypatch, mode):
    from datetime import date
    from competitive_intel.config import LLMSettings
    from competitive_intel.infrastructure.agent.analytical_writer import AnalyticalWriter
    from competitive_intel.infrastructure.agent.narrative_writer import isolated_budget, reviewed_rates
    from competitive_intel.infrastructure.budgeted_transport import BudgetedSession
    import requests
    class Clock(date):
        @classmethod
        def today(cls): return cls(2026, 10, 27)
    monkeypatch.setattr('competitive_intel.infrastructure.agent.narrative_writer.date', Clock)
    task = spec(); analysis = sample(); packet = writing_packet(task, analysis)
    payload = fixture_payload(packet); calls = []
    class Response:
        status_code = 503 if mode == 'http' else 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def iter_content(self, size):
            if mode == 'oversize': yield b'x' * 96001; return
            yield json.dumps(dict(model='deepseek-flash', usage=dict(prompt_tokens=100, completion_tokens=100),
                choices=[dict(finish_reason='length' if mode=='length' else 'stop', message=dict(content='bad json' if mode=='json' else json.dumps(payload)))])).encode()
    class Transport:
        def post(self, url, **kwargs):
            calls.append(kwargs)
            if mode == 'timeout': raise requests.Timeout('private secret')
            assert 'variant_ids' not in kwargs['json']['messages'][0]['content']
            assert kwargs['allow_redirects'] is False
            assert len(json.loads(kwargs['json']['messages'][1]['content'])['facts']) == len(packet['facts'])
            return Response()
    budget=isolated_budget()
    writer=AnalyticalWriter(LLMSettings(model='deepseek-flash', endpoint='https://api.deepseek.com', api_key='test-secret'),
        BudgetedSession(budget,'synthesis',session=Transport(),rates=reviewed_rates()),
        live_authorized=True,attempt_file=tmp_path/'attempt.json')
    view=compose_analysis(task,analysis,writer,reviews=reviewed(payload,packet))
    assert analysis['ai_status'] == ('HUMAN_VALIDATED' if mode=='ok' else 'FAILED')
    assert len(calls)==1 and budget.used['models']==1 and budget.used['tokens']==20000
    assert budget.used['cost_microusd']==9600
    assert budget.used['searches']==budget.used['fetches']==0
    with pytest.raises(ValueError,match='ALREADY_ATTEMPTED'): writer.write(packet)


def test_legitimate_ids_do_not_authorize_wrong_attribution_or_new_claims():
    packet=writing_packet(spec(),sample()); payload=fixture_payload(packet)
    reviews=reviewed(payload,packet)
    payload['units'][0]['text']='Alpha 支持离线访问全部内容，Beta 支持自动生成视频。'
    accepted,diagnostics=validate_document(payload,packet,reviews)
    assert len(accepted)==3 and diagnostics[0]['code']=='SEMANTIC_REVIEW_REQUIRED'


def test_whitespace_is_server_owned_but_missing_section_stays_pending():
    task=spec(); a=sample(); packet=writing_packet(task,a); payload=fixture_payload(packet)
    reviews=reviewed(payload,packet)
    payload['units'][0]['text']='\n  '+payload['units'][0]['text']+'\n'
    assert len(validate_document(payload,packet,reviews)[0])==4
    payload['units'][3]['section']='conclusions'
    compose_analysis(task,a,SimpleNamespace(write=lambda _:payload),reviews=reviews)
    assert a['delivery_status']=='REVIEW_REQUIRED'

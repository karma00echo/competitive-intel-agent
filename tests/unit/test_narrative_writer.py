from copy import deepcopy
from dataclasses import replace
from datetime import date
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import requests

from competitive_intel.config import LLMSettings
from competitive_intel.domain.narrative import prepare_narrative, variants, validate_narrative, write_narrative
from competitive_intel.domain.task_budget import BudgetLimits, TaskBudget
from competitive_intel.infrastructure.agent.narrative_writer import NarrativeWriter, isolated_budget
from competitive_intel.infrastructure.budgeted_transport import BudgetedSession, CostRates
from test_report_writing import sample

TASK = SimpleNamespace(output_language="zh-CN")


@pytest.fixture(autouse=True)
def reviewed_test_clock(monkeypatch):
    # Deployment review expires in real time; unit fixtures are reproducible.
    class ReviewedDate(date):
        @classmethod
        def today(cls): return cls(2026, 10, 27)
    monkeypatch.setattr("competitive_intel.infrastructure.agent.narrative_writer.date", ReviewedDate)


def reply(request):
    sections = []
    for name, ids in request["sections"].items():
        ps = []
        for cid in ids:
            kind, text, evidence = request["claims"][cid]
            choices = variants(text)
            ps.append(dict(claim_ids=[cid], variant_ids=[len(choices)-1], evidence_ids=sorted(evidence), text=choices[-1]))
        sections.append(dict(id=name, paragraphs=ps))
    return dict(document_hash=request["document_hash"], sections=sections)


class Response:
    status_code = 200
    def __init__(self, body): self.body = body
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size): yield self.body


class Transport:
    def __init__(self, mode="ok"): self.calls=0; self.mode=mode; self.kwargs=None
    def post(self, url, **kwargs):
        self.calls += 1; self.kwargs = kwargs
        assert kwargs["allow_redirects"] is False
        assert kwargs["json"]["thinking"] == {"type": "disabled"}
        assert "tools" not in kwargs["json"]
        if self.mode == "timeout": raise requests.Timeout("private diagnostic")
        request = json.loads(kwargs["json"]["messages"][1]["content"])
        payload = reply(request)
        if self.mode == "price": payload["sections"][0]["paragraphs"][0]["text"] += "每月只需1美元"
        content = "invalid JSON" if self.mode == "json" else json.dumps(payload,ensure_ascii=False)
        data = dict(model="deepseek-flash", choices=[dict(finish_reason="length" if self.mode == "length" else "stop", message=dict(content=content))], usage=dict(prompt_tokens=2000,completion_tokens=1500,total_tokens=3500))
        response = Response(b"x"*96001 if self.mode == "oversize" else json.dumps(data,ensure_ascii=False).encode())
        if self.mode == "http": response.status_code = 503
        return response
    def close(self): pass


def writer(tmp_path, mode="ok", **changes):
    settings = LLMSettings(model="deepseek-flash", endpoint="https://api.deepseek.com", api_key="fixture-secret-never-live")
    transport = Transport(mode)
    budget = changes.pop("budget", isolated_budget())
    wrapped = BudgetedSession(budget,"synthesis",session=transport,rates=CostRates(search=0))
    w = NarrativeWriter(settings,wrapped,live_authorized=True,attempt_file=tmp_path/"attempt.json",**changes)
    return w, transport


def test_paraphrase_and_grouping_keep_evidence_and_boundaries():
    view,catalog,req = prepare_narrative(TASK,sample())
    result = reply(req)
    section=result["sections"][0]; first,second=section["paragraphs"][:2]
    merged=dict(claim_ids=first["claim_ids"]+second["claim_ids"], variant_ids=first["variant_ids"]+second["variant_ids"],
                evidence_ids=sorted(set(first["evidence_ids"]+second["evidence_ids"])),text=first["text"]+"\n"+second["text"])
    section["paragraphs"][:2]=[merged]
    assert validate_narrative(result,req,catalog)
    out=write_narrative(TASK,sample(),SimpleNamespace(write=lambda r:result))
    assert out["status"]==view["status"]=="PARTIAL"
    assert out["sections"][2:4]==view["sections"][2:4]
    assert out["references"]==view["references"]
    assert out["writing"]["narrative"]["status"]=="VALIDATED_FINITE_PARAPHRASE"


@pytest.mark.parametrize("case",["price","advantage","unsourced","wrong_id","mismatch","omit","schema","variant","wrong_section","duplicate"])
def test_new_assertions_and_wrong_citations_rejected(case):
    view,cat,req=prepare_narrative(TASK,sample()); payload=reply(req)
    p=payload["sections"][2]["paragraphs"][0]
    if case=="price": p["text"]+="价格为99美元。"
    if case=="advantage": p["text"]+="更适合大企业，性能领先。"
    if case=="unsourced": p.update(text="全球市场第一。",evidence_ids=[])
    if case=="wrong_id": p["evidence_ids"]=["o-unknown"]
    if case=="mismatch": p["evidence_ids"]=payload["sections"][0]["paragraphs"][0]["evidence_ids"]
    if case=="omit": payload["sections"][0]["paragraphs"].pop()
    if case=="schema": p["verified"]=True
    if case=="variant": p["variant_ids"]=[999]
    if case=="wrong_section": p["claim_ids"]=payload["sections"][0]["paragraphs"][0]["claim_ids"]
    if case=="duplicate": payload["sections"][2]["paragraphs"].append(deepcopy(p))
    with pytest.raises(ValueError): validate_narrative(payload,req,cat)
    out=write_narrative(TASK,sample(),SimpleNamespace(write=lambda r:payload))
    assert out["sections"]==view["sections"]
    assert out["writing"]["narrative"]["status"]=="REJECTED_OR_UNAVAILABLE"


@pytest.mark.parametrize("mode",["ok","price","json","oversize","http","timeout","length"])
def test_single_request_failure_and_safe_fallback(tmp_path,mode):
    w,t=writer(tmp_path,mode); a=sample(); before=deepcopy(a)
    out=write_narrative(TASK,a,w)
    assert a==before and t.calls==1
    assert w.transport.budget.used["tokens"]==20000
    assert w.transport.budget.used["cost_microusd"]==9600
    assert w.transport.budget.used["models"]==1
    assert w.transport.budget.used["searches"]==w.transport.budget.used["fetches"]==0
    assert "private diagnostic" not in str(out)
    assert out["writing"]["narrative"]["status"]==("VALIDATED_FINITE_PARAPHRASE" if mode=="ok" else "REJECTED_OR_UNAVAILABLE")
    with pytest.raises(ValueError,match="ALREADY_ATTEMPTED"): w.write(prepare_narrative(TASK,a)[2])
    assert t.calls==1
    new,other=writer(tmp_path)
    with pytest.raises(FileExistsError): new.write(prepare_narrative(TASK,a)[2])
    assert other.calls==0


def test_limits_block_before_http(tmp_path):
    w,t=writer(tmp_path); req=prepare_narrative(TASK,sample())[2]
    with pytest.raises(ValueError,match="INPUT_LIMIT"): w.write({"large":"中"*16000})
    assert t.calls==0 and not w.attempt_file.exists()
    w.transport.budget=TaskBudget(replace(isolated_budget().limits,cost_microusd=9599))
    with pytest.raises(ValueError,match="INSUFFICIENT_BUDGET"): w.write(req)
    assert t.calls==0


def test_review_authorization_and_retries(tmp_path):
    w,t=writer(tmp_path); req=prepare_narrative(TASK,sample())[2]
    with pytest.raises(ValueError,match="EXPIRED"): w.preflight(req,today=date(2026,11,5))
    w.live_authorized=False
    with pytest.raises(PermissionError): w.write(req)
    assert t.calls==0
    w.settings=replace(w.settings,model="unknown")
    with pytest.raises(ValueError,match="UNREVIEWED"): w.preflight(req)
    w.settings=replace(w.settings,model="deepseek-flash")
    w.transport.rates=CostRates(input_per_million=1)
    with pytest.raises(ValueError,match="UNREVIEWED_RATES"): w.preflight(req)
    w.transport.rates=CostRates(); s=requests.Session();s.mount("https://",requests.adapters.HTTPAdapter(max_retries=1));w.transport.session=s
    with pytest.raises(ValueError,match="RETRIES_FORBIDDEN"): w.preflight(req)


def test_run38_local_fixture_when_available(tmp_path):
    path=Path(__file__).resolve().parents[2]/"build/run38-quality/original.json"
    if not path.exists(): pytest.skip("Private historical fixture is local-only")
    from competitive_intel.domain.analysis_task import AnalysisTaskSpec
    source=path.read_bytes();a=json.loads(source)
    assert len(a["matrix"]["facts"])==len(a["matrix"]["evidence"])==17
    task=AnalysisTaskSpec.model_validate(a["task"]).model_copy(update={"output_language":"zh-CN"})
    w,t=writer(tmp_path)
    before=deepcopy(a);out=write_narrative(task,a,w)
    assert out["writing"]["narrative"]["status"]=="VALIDATED_FINITE_PARAPHRASE"
    assert out["status"]=="PARTIAL" and a==before and path.read_bytes()==source
    assert len(out["references"])==17
    assert any("官方定位是" in p for p in out["sections"][1]["paragraphs"])


def test_concurrent_instances_share_durable_guard(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    first, a = writer(tmp_path); second, b = writer(tmp_path)
    req = prepare_narrative(TASK, sample())[2]
    def run(w):
        try: w.write(req); return "sent"
        except FileExistsError: return "blocked"
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, [first, second]))
    assert sorted(results)==["blocked","sent"] and a.calls+b.calls==1


def test_reasonable_but_unreviewed_paraphrase_is_rejected():
    _,cat,req=prepare_narrative(TASK,sample());payload=reply(req)
    payload["sections"][0]["paragraphs"][0]["text"]="研究依据来自已验证的官方事实。"
    with pytest.raises(ValueError,match="UNSUPPORTED_ASSERTION"):
        validate_narrative(payload,req,cat)

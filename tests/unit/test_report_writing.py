"""Synthetic evidence only; no provider, private replay data or database."""
from copy import deepcopy
from types import SimpleNamespace
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from competitive_intel.domain.comparison_presentation import reading_view
from competitive_intel.domain.report_writing import (
    apply_writing_provider, validate_writing, writing_request,
)
from competitive_intel.services.competitive_report_service import render_competitive_report
from test_competitive_matrix import matrix, row, price
from test_comparison_reading import analysis


def sample():
    def feature(name, description):
        return dict(feature_name=name, normalized_feature_name=name.casefold(), feature_description=description,
                    feature_category="AI", status="UNKNOWN", availability=None, related_plan=None)
    a = "Build AI agents and delegate entire issues."
    b = "Brainstorm new ideas and condense lengthy texts with AI."
    c = "Run commands and set automated rules."
    d = "Turn conversations and customer feedback into actionable issues."
    e = "Connect apps and services and sync and manage your tasks."
    records = {1: [row(1, value=feature("AI automations", a), quote="AI automations. " + a),
                   row(1, number=2, value=feature("Integrations", d), quote="Integrations. " + d)],
               2: [row(2, value=feature("AI", b), quote=b),
                   row(2, number=2, value=feature("Automation", c), quote="Automation. " + c),
                   row(2, number=3, value=feature("Integrations", e), quote="Integrations. " + e)]}
    m = matrix(records, dimensions=("core_features", "pricing"))
    m["products"] = m["products"][:2]
    return analysis(m)


def view(a=None, language="zh-CN"):
    return reading_view(SimpleNamespace(output_language=language), a or sample())


def test_chinese_body_uses_grounded_phrases_and_deduplicated_workflow_inferences():
    a = sample()
    before = deepcopy(a)
    v = view(a)
    assert a == before
    assert len(v["capabilities"]) == 3
    assert len(v["writing"]["editable_claim_ids"]) == 2  # AI + automation share one fact
    body = str(v["sections"])
    assert "完整事项委派" in body
    assert "内容准备与整理" in body and "信息如何进入任务流程" in body
    assert "Build AI agents" not in body
    assert "可用状态：未知" not in body
    assert "端到端执行" in body
    assert v["status"] == "PARTIAL"
    for phrase in v["writing"]["phrases"]:
        assert phrase["source_span"] in a["matrix"]["evidence"][phrase["evidence_id"]]["quote"]
        assert phrase["field_span"] in a["matrix"]["facts"][phrase["fact_id"]]["value"][phrase["field"]]
    for claim in v["writing"]["claims"]:
        if claim["kind"] in {"FACT", "ANALYSIS_INFERENCE"}:
            assert claim["fact_ids"] and claim["evidence_ids"]
            assert set(claim["evidence_ids"]) == {eid for fid in claim["fact_ids"] for eid in a["matrix"]["facts"][fid]["evidence_ids"]}
        for fid in claim["finding_ids"]:
            finding = next(f for f in v["writing"]["findings"] if f["id"] == fid)
            assert set(finding["fact_ids"]) <= set(claim["fact_ids"])


@pytest.mark.parametrize("mutation", ["price", "advantage", "unsourced", "evidence", "foreign_evidence", "fact", "finding", "duplicate", "missing", "hash", "schema", "kind"])
def test_editor_rejects_fabrication_even_with_valid_citations(mutation):
    v = view()
    req = writing_request(v)
    payload = dict(document_hash=req["document_hash"], claims=deepcopy(req["claims"]))
    claim = payload["claims"][0]
    if mutation == "price": claim["text"] += " Alpha 每月仅需 1 美元。"
    if mutation == "advantage": claim["text"] += " Alpha 更适合企业，具备竞争优势。"
    if mutation == "unsourced": claim.update(text="市场份额第一", evidence_ids=[], fact_ids=[], finding_ids=[])
    if mutation == "evidence": claim["evidence_ids"] = ["o-999999"]
    if mutation == "foreign_evidence": claim["evidence_ids"] = payload["claims"][1]["evidence_ids"]
    if mutation == "fact": claim["fact_ids"] = ["f-invented"]
    if mutation == "finding": claim["finding_ids"] = ["finding-999"]
    if mutation == "duplicate": payload["claims"][1] = deepcopy(claim)
    if mutation == "missing": payload["claims"].pop()
    if mutation == "hash": payload["document_hash"] = "stale"
    if mutation == "schema": payload["verified"] = True
    if mutation == "kind": claim["kind"] = "FACT"
    with pytest.raises(ValueError, match="WRITING_"):
        validate_writing(payload, req)
    result = apply_writing_provider(v, SimpleNamespace(write=lambda _: payload))
    assert result["sections"] == v["sections"]
    assert result["writing"]["status"] == "REJECTED_EDITOR_OUTPUT"


def test_editor_reordering_contract_and_failure_are_safe():
    v = view()
    before = deepcopy(v)
    def write(request):
        return dict(document_hash=request["document_hash"], claims=list(reversed(request["claims"])))
    result = apply_writing_provider(v, SimpleNamespace(write=write))
    old = v["sections"][4]["paragraphs"]
    assert result["sections"][4]["paragraphs"] == old[:2][::-1] + old[2:]
    assert v == before
    def broken(request):
        request["claims"][0]["text"] = "Invented superiority"
        raise RuntimeError("private provider exception")
    rejected = apply_writing_provider(v, SimpleNamespace(write=broken))
    assert rejected["sections"] == v["sections"]
    assert "private provider exception" not in str(rejected)


@pytest.mark.parametrize("field,value", [("quote", ""), ("confidence", None), ("confidence", True), ("confidence", 2), ("collected_at", None), ("verification_status", "PENDING"), ("product_id", 999), ("url", "javascript:alert(1)"), ("id", "o-foreign")])
def test_missing_or_wrong_provenance_cannot_support_writing(field, value):
    a = sample()
    next(iter(a["matrix"]["evidence"].values()))[field] = value
    with pytest.raises(ValueError): view(a)


def test_quote_only_claims_and_negated_or_conflicted_facts_cannot_be_translated():
    a = sample()
    f = next(iter(a["matrix"]["facts"].values()))
    f["value"]["feature_description"] = "Other verified functionality."
    assert not any(p["fact_id"] == f["id"] for p in view(a)["writing"]["phrases"])
    f["value"]["feature_description"] = "Does not build AI agents or delegate entire issues."
    assert not any(p["fact_id"] == f["id"] for p in view(a)["writing"]["phrases"])
    f["verification_status"] = "SOURCE_CONFLICT"
    assert all(f["id"] not in c["fact_ids"] for c in view(a)["writing"]["claims"])


def test_price_quotes_never_fill_missing_structured_price_or_rank():
    a = sample()
    for e in a["matrix"]["evidence"].values():
        e["quote"] += " Pro $99 per user monthly."
    v = view(a)
    assert "$99" not in str(v["sections"])
    assert "尚无确认的价格" in str(v["sections"])
    assert not any(c["kind"] == "FACT" for c in v["writing"]["claims"] if "价格" in c["text"])


def test_price_basis_and_english_are_preserved():
    m = matrix({1: [price(1, currency=None)], 2: [price(2)]}, dimensions=("pricing",))
    v = view(analysis(m))
    assert "币种：未明确" in str(v["sections"])
    assert "暂不比较高低" in str(v["sections"])
    en = view(language="en")
    assert "Build AI agents" in str(en["sections"])
    assert "Competitive differences" in str(en["sections"])


def test_markdown_uses_persisted_document_and_real_source_anchors():
    a = sample()
    a["presentation"] = view(a)
    md = render_competitive_report(SimpleNamespace(output_language="en"), a)
    assert "执行摘要" in md and "Executive summary" not in md
    assert "[1](#source-1)" in md and '<a id="source-1"></a>' in md
    assert "https://product1.example/1" in md
    assert "evidence-writing-v1" in md
    for section in a["presentation"]["sections"]:
        assert section["heading"] in md
        for p in section["paragraphs"]:
            assert p.split(" [")[0] in md


def test_unknown_language_coverage_is_disclosed_not_guessed():
    a = sample()
    f = next(iter(a["matrix"]["facts"].values()))
    f["value"]["feature_description"] = "A novel capability outside the editorial vocabulary."
    v = view(a)
    assert "详细内容请查阅来源原文" in str(v["sections"])
    assert "有限的" in str(v["sections"])


def test_negation_is_scoped_without_suppressing_other_supported_sentences():
    a = sample()
    f = next(iter(a["matrix"]["facts"].values()))
    text = "Streamline code reviews. Keep work moving without sacrificing quality."
    f["value"]["feature_description"] = text
    a["matrix"]["evidence"][f["evidence_ids"][0]]["quote"] = text
    assert any(p["rule"] == "review" and p["fact_id"] == f["id"] for p in view(a)["writing"]["phrases"])


@pytest.mark.parametrize("language", ["zh-CN", "en"])
def test_production_ui_consumes_exact_document_with_clickable_citations(language):
    node = shutil.which("node")
    if not node: pytest.skip("Node is required for the production JavaScript renderer test")
    root = Path(__file__).resolve().parents[2]
    a = sample()
    a["presentation"] = view(a, language)
    a["presentation"]["references"][0]["quote"] += '<script>alert("source")</script>'
    result = subprocess.run([node, str(root / "tests/fixtures/report_reading_dom.cjs"),
                             str(root / "src/competitive_intel/web/static/app.js")],
                            input=json.dumps(dict(content_json=a)), text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "text parity" in result.stdout

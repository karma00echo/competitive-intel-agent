"""Open prose with provenance gates, never ID-based semantic certification.

Free prose needs an independent human review tied to the entire evidence packet.
Unreviewed or rejected prose is audit data, not published product assertions.
"""
from copy import deepcopy
from hashlib import sha256
import json
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from typing import Literal
from .comparison_presentation import reading_view
from .competitive_findings import build_findings


class Unit(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    section: Literal["overview", "differences", "conclusions", "recommendations"]
    kind: Literal["comparison", "inference", "recommendation"]
    text: str = Field(min_length=10, max_length=1800)
    fact_ids: list[str] = Field(max_length=20)
    finding_ids: list[str] = Field(max_length=12)
    premise: str = Field(max_length=600)
    verification: str = Field(max_length=600)


class Document(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    units: list[Unit] = Field(min_length=4, max_length=16)


def digest(value):
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def writing_packet(task, analysis, goal=""):
    matrix = analysis["matrix"]
    return dict(language=task.output_language, goal=goal, task=task.model_dump(),
                facts={fid: {k: f[k] for k in ("product_id", "product", "category", "value", "verification_status", "evidence_ids")}
                       for fid, f in matrix["facts"].items()},
                evidence={eid: {k: e[k] for k in ("quote", "url", "collected_at")}
                          for eid, e in matrix["evidence"].items()},
                findings=[{k: f[k] for k in ("id", "kind", "fact_ids")} for f in build_findings(matrix)["findings"]], gaps=deepcopy(matrix["gaps"]),
                coverage=analysis["status"])


def validate_document(payload, packet, reviews=None):
    """Reviews are server-owned hash->human rationale, never accepted from a model.

    Numeric/absolute-advantage guards are deliberately conservative MVP rules.
    They are not a general entailment detector. No unreviewed free prose is trusted.
    """
    try:
        document = Document.model_validate(payload)
    except ValidationError:
        return [], [{"code": "STRUCTURE_INVALID", "stage": "format"}]
    findings = {f["id"]: f for f in packet["findings"]}
    accepted, diagnostics, seen = [], [], set()
    for index, unit in enumerate(document.units):
        data = unit.model_dump()
        # Formatting normalization does not invent IDs or change propositions.
        data["text"] = " ".join(data["text"].split())
        code = None
        ids = set(unit.fact_ids)
        if any(fid not in findings for fid in unit.finding_ids):
            code = "FINDING_UNKNOWN"
        else:
            ids.update(fid for finding in unit.finding_ids for fid in findings[finding]["fact_ids"])
        facts = packet["facts"]
        if not ids or any(fid not in facts or facts[fid]["verification_status"] != "CONFIRMED" for fid in ids):
            code = "FACT_UNSUPPORTED"
        evidence = sorted({e for fid in ids if fid in facts for e in facts[fid]["evidence_ids"]})
        if code is None and (not evidence or any(e not in packet["evidence"] for e in evidence)):
            code = "EVIDENCE_UNSUPPORTED"
        prose = " ".join([data["text"], unit.premise, unit.verification])
        # Pricing remains exclusively in the structured, verified table.
        if re.search(r"\d|[$€£¥￥%]|https?://|\[\d+\]", prose):
            code = "NUMERIC_OR_EXTERNAL_ASSERTION"
        if re.search(r"更适合|优于|最佳|领先|最强|市场份额|保证|better than|best|superior|market share", prose, re.I):
            code = "UNSUPPORTED_RANKING"
        if unit.kind == "comparison" and len({facts[f]["product_id"] for f in ids if f in facts}) < 2:
            code = "COMPARISON_REQUIRES_PEERS"
        if unit.kind in {"inference", "recommendation"} and len(unit.premise) < 8:
            code = "PREMISE_REQUIRED"
        if unit.kind == "recommendation" and (len(unit.verification) < 8 or unit.section != "recommendations"):
            code = "VERIFICATION_REQUIRED"
        if unit.section == "recommendations" and unit.kind != "recommendation":
            code = "RECOMMENDATION_KIND_REQUIRED"
        if data["text"] in seen:
            code = "DUPLICATE_PARAGRAPH"
        seen.add(data["text"])
        fingerprint = digest({"packet": packet, "unit": data})
        if code is None and not (reviews or {}).get(fingerprint):
            code = "SEMANTIC_REVIEW_REQUIRED"
        diagnostics.append(dict(index=index, code=code or "HUMAN_REVIEWED", fingerprint=fingerprint))
        if code is None:
            accepted.append(dict(**data, id=f"analysis-{index + 1}", evidence_ids=evidence,
                                 fact_ids_resolved=sorted(ids), review=(reviews or {})[fingerprint]))
    return accepted, diagnostics


def compose_analysis(task, analysis, provider, *, goal="", reviews=None):
    view = reading_view(task, analysis)
    packet = writing_packet(task, analysis, goal)
    audit = dict(schema="analytical-writing-v1", packet_hash=digest(packet),
                 goal=goal, origin=getattr(provider, "origin", "model"), status="FAILED", diagnostics=[])
    try:
        payload = provider.write(packet)
        accepted, diagnostics = validate_document(payload, packet, reviews)
        audit.update(candidate=payload, diagnostics=diagnostics, usage=getattr(provider, "usage", None),
                     raw_response=getattr(provider, "raw_output", None))
        if getattr(provider, "revision", None):
            audit["editorial_revision"] = deepcopy(provider.revision)
    except Exception as exc:
        accepted = []
        code = "JSON_INVALID" if isinstance(exc, json.JSONDecodeError) else "PROVIDER_OR_JSON_FAILURE"
        if isinstance(exc, ValueError) and re.fullmatch(r"(?:NARRATIVE|FIXTURE|REVIEWED)_[A-Z_]+", str(exc)):
            code = str(exc)
        audit["diagnostics"] = [{"code": code}]
        audit["raw_response"] = getattr(provider, "raw_output", None)
    covered = {u["section"] for u in accepted}
    complete = covered == {"overview", "differences", "conclusions", "recommendations"} and all(
        d["code"] == "HUMAN_REVIEWED" for d in audit["diagnostics"])
    audit["status"] = "HUMAN_VALIDATED" if complete else "REVIEW_REQUIRED" if "candidate" in audit else "FAILED"
    fixture = audit["origin"] == "fixture"
    if complete and fixture:
        audit["status"] = "FIXTURE_VALIDATED"
    audit["accepted"] = accepted
    zh = task.output_language == "zh-CN"
    labels = {e["id"]: e["label"] for e in view["references"]}
    def paragraphs(section):
        out = []
        for u in accepted:
            if u["section"] != section: continue
            prefix = {"comparison": "比较分析：", "inference": "条件性推断：", "recommendation": "策略建议："}[u["kind"]] if zh else u["kind"] + ": "
            text = prefix + u["text"]
            if u["premise"]: text += (" 前提：" if zh else " Premise: ") + u["premise"]
            if u["verification"]: text += (" 验证方式：" if zh else " Verification: ") + u["verification"]
            out.append(text + " " + " ".join(f"[{labels[e]}]" for e in u["evidence_ids"]))
        return out or [("本节 AI 正文尚未通过证据语义审核，暂不发布其判断。" if zh else "AI prose has not passed semantic review; its claims are withheld.")]
    # Keep verified matrices/pricing/limitations; replace repetitive narrative.
    old = view["sections"]
    scope = ("研究范围：" if zh else "Research scope: ") + ", ".join([task.target, *task.competitors])
    status_text = (("Fixture 工程演示；不代表真实模型写作验收。" if zh else "Fixture demonstration, not live model acceptance.") if audit["origin"] == "fixture" else "")
    status_text += (" 正文已通过 Fixture 核查。" if complete and fixture else " AI 正文已人工核查。" if complete else " AI 正文待核查，当前不构成已验收的 AI 报告。") if zh else (" Fixture reviewed." if complete and fixture else " AI prose human-reviewed." if complete else " AI prose pending review.")
    limitations = deepcopy(old[6:])
    for section in limitations:
        section["paragraphs"] = [p for p in section.get("paragraphs", []) if not p.startswith((
            "中文采用有限的、可核对原文片段的表达规则", "本报告区分官方事实说明、规则约束的分析推断和待核查问题。",
            "Chinese wording uses finite, auditable span rules;",
            "This report distinguishes official descriptions, rule-bound inferences and follow-up questions."))]
    limitations.append(dict(heading="分析验证边界" if zh else "Analysis validation boundary", paragraphs=[
        "事实表沿用确认记录；自由分析须经独立语义审核。引用存在检查不能单独证明正文真实，未通过审核的判断不会作为结论发布。" if zh else
        "Fact tables retain confirmed records. Free prose requires independent semantic review; existing citation IDs alone do not establish truth. Unreviewed claims are withheld."]))
    scope_paragraphs = [scope, ("研究问题：" if zh else "Research question: ") + goal, status_text] if goal else [scope, status_text]
    view["sections"] = [dict(heading="研究范围与交付状态" if zh else "Scope and delivery", paragraphs=scope_paragraphs),
        dict(heading="竞品概况与执行摘要" if zh else "Overview and executive summary", paragraphs=paragraphs("overview")),
        old[2], old[3], dict(heading="核心差异" if zh else "Core differences", paragraphs=paragraphs("differences")),
        dict(heading="综合结论" if zh else "Conclusions", paragraphs=paragraphs("conclusions")),
        dict(heading="产品策略建议" if zh else "Strategy recommendations", paragraphs=paragraphs("recommendations")), *limitations]
    view["executive_summary"] = "\n".join(paragraphs("overview"))
    view["writing"]["analytical"] = audit
    view["writing"]["status"] = audit["status"]
    analysis["ai_status"] = audit["status"]
    analysis["delivery_status"] = "DEMO_READY" if complete and fixture else "READY" if complete else "REVIEW_REQUIRED"
    return view

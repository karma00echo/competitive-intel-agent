"""Finite paraphrase grammar, not a general hallucination/entailment detector."""
from copy import deepcopy
from hashlib import sha256
import json

from .comparison_presentation import reading_view

SECTIONS = {"summary": 0, "positioning": 1, "differences": 4, "conclusions": 5}
# Each change is reviewed as an equivalent expression, never a new proposition.
PARAPHRASES = (("定位为", "官方定位是"), ("的材料侧重", "的官方说明着重介绍"),
              ("后续核查应使用", "下一步建议使用"), ("暂不比较高低", "目前不宜比较价格高低"))


def variants(text):
    alternate = text
    for before, after in PARAPHRASES:
        alternate = alternate.replace(before, after)
    return [text] if alternate == text else [text, alternate]


def prepare_narrative(task, analysis):
    # Rebuild from the validated matrix, not a caller-supplied presentation/catalog.
    view = reading_view(task, analysis)
    if view["language"] != "zh-CN":
        raise ValueError("NARRATIVE_CHINESE_REQUIRED")
    refs = {e["id"]: e["label"] for e in view["references"]}
    catalog, sections = {}, {}
    for name, index in SECTIONS.items():
        ids = []
        for paragraph in view["sections"][index]["paragraphs"]:
            matches = [c for c in view["writing"]["claims"] if c["text"] +
                       (" " + " ".join(f"[{refs[e]}]" for e in c["evidence_ids"]) if c["evidence_ids"] else "") == paragraph]
            if not matches:
                raise ValueError("NARRATIVE_UNMAPPED_PARAGRAPH")
            c = matches[0]
            catalog[c["id"]] = deepcopy(c)
            ids.append(c["id"])
        sections[name] = ids
    evidence_ids = {eid for c in catalog.values() for eid in c["evidence_ids"]}
    request = dict(sections=sections,
                   claims={cid: [c["kind"], c["text"], c["evidence_ids"]] for cid, c in catalog.items()},
                   paraphrases=PARAPHRASES,
                   evidence={e["id"]: e["quote"] for e in view["references"] if e["id"] in evidence_ids})
    request["document_hash"] = sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return view, catalog, request


def validate_narrative(payload, request, catalog):
    if not isinstance(payload, dict) or set(payload) != {"document_hash", "sections"} or payload["document_hash"] != request["document_hash"]:
        raise ValueError("NARRATIVE_SCHEMA")
    sections = payload["sections"]
    if not isinstance(sections, list) or len(sections) != len(SECTIONS):
        raise ValueError("NARRATIVE_SECTIONS")
    seen_sections = set()
    for section in sections:
        if not isinstance(section, dict) or set(section) != {"id", "paragraphs"}:
            raise ValueError("NARRATIVE_SECTION_SCHEMA")
        name = section["id"]
        if not isinstance(name, str) or name not in SECTIONS or name in seen_sections:
            raise ValueError("NARRATIVE_SECTION_ID")
        seen_sections.add(name)
        paragraphs = section["paragraphs"]
        if not isinstance(paragraphs, list) or not 1 <= len(paragraphs) <= len(request["sections"][name]):
            raise ValueError("NARRATIVE_PARAGRAPHS")
        seen = []
        for p in paragraphs:
            if not isinstance(p, dict) or set(p) != {"claim_ids", "variant_ids", "evidence_ids", "text"}:
                raise ValueError("NARRATIVE_PARAGRAPH_SCHEMA")
            ids, choices = p["claim_ids"], p["variant_ids"]
            if not isinstance(ids, list) or not 1 <= len(ids) <= 3 or not isinstance(choices, list) or len(choices) != len(ids):
                raise ValueError("NARRATIVE_CLAIMS")
            texts, evidence = [], set()
            for cid, choice in zip(ids, choices):
                if not isinstance(cid, str) or cid not in request["sections"][name] or cid in seen:
                    raise ValueError("NARRATIVE_CLAIM_SCOPE")
                options = variants(catalog[cid]["text"])
                if type(choice) is not int or not 0 <= choice < len(options):
                    raise ValueError("NARRATIVE_VARIANT")
                texts.append(options[choice]); evidence.update(catalog[cid]["evidence_ids"]); seen.append(cid)
            if p["text"] != "\n".join(texts) or p["evidence_ids"] != sorted(evidence):
                raise ValueError("NARRATIVE_UNSUPPORTED_ASSERTION")
        if set(seen) != set(request["sections"][name]):
            raise ValueError("NARRATIVE_OMITTED_BOUNDARY")
    return deepcopy(sections)


def write_narrative(task, analysis, provider):
    view, catalog, request = prepare_narrative(task, analysis)
    try:
        payload = provider.write(deepcopy(request))
        sections = validate_narrative(payload, request, catalog)
    except Exception:
        view["writing"]["narrative"] = {"status": "REJECTED_OR_UNAVAILABLE", "fallback": "OFFLINE_RULES"}
        return view
    refs = {e["id"]: e["label"] for e in view["references"]}
    for section in sections:
        # Render citations per claim, even when a model groups several claims.
        paragraphs = []
        for p in section["paragraphs"]:
            parts = []
            for cid, variant in zip(p["claim_ids"], p["variant_ids"]):
                c = catalog[cid]
                parts.append(variants(c["text"])[variant] + (" " + " ".join(f"[{refs[e]}]" for e in c["evidence_ids"]) if c["evidence_ids"] else ""))
            paragraphs.append("\n".join(parts))
        view["sections"][SECTIONS[section["id"]]]["paragraphs"] = paragraphs
    view["executive_summary"] = "\n".join(view["sections"][0]["paragraphs"])
    view["writing"]["narrative"] = dict(status="VALIDATED_FINITE_PARAPHRASE", sections=sections,
                                       document_hash=request["document_hash"], claims=catalog)
    return view

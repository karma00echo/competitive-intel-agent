"""Evidence-bound reading model; labels are translations, source claims are not.

Category membership is an auditable lexical inference from quoted feature names,
not a claim of equivalent capabilities, completeness, suitability or quality.
"""

import re
from .competitive_matrix import utc


CATEGORIES = {
    "ai": ("AI 能力", "AI", r"\bai\b|artificial intelligence|人工智能"),
    "automation": ("自动化", "Automation", r"\bautomat(?:ion|ions|e|ed|ically)\b|自动化"),
    "integration": ("集成", "Integrations", r"\bintegrations?\b|集成"),
    "planning": ("项目规划", "Project planning", r"\bplanning\b|\broadmaps?\b|项目规划"),
    "tasks": ("任务管理", "Task management", r"\bdue dates?\b|\bchecklists?\b|\bcustom fields?\b|任务管理"),
    "collaboration": ("协作与文档", "Collaboration and documents", r"\bcollaboration\b|\battachments?\b|协作"),
    "development": ("开发交付", "Development delivery", r"\bcode review\b|\bbuild,? review\b|代码审查"),
}

# Small, product-independent reading glossary. Each annotation retains the exact
# matching source span; it never substitutes for the original fact or quotation.
ACTION_LABELS = (
    ("AI 智能体", "AI agents", r"\bAI agents?\b"),
    ("任务委派", "Issue delegation", r"\bdelegate entire issues\b"),
    ("创意构思", "Idea brainstorming", r"\bbrainstorm new ideas\b"),
    ("文本精简", "Text condensation", r"\bcondense lengthy texts\b"),
    ("自动化规则", "Automation rules", r"\bautomated rules\b"),
    ("命令执行", "Command execution", r"\brun commands\b"),
    ("反馈转为事项", "Feedback intake", r"\bturn conversations and customer feedback into actionable issues\b"),
    ("路线图", "Roadmaps", r"\broadmaps?\b"),
    ("代码审查", "Code review", r"\bcode reviews?\b"),
    ("任务拆分", "Task decomposition", r"\bbreak big tasks into small ones\b"),
    ("截止日期", "Due dates", r"\bdue dates?\b"),
    ("附件", "Attachments", r"\battachments?\b"),
    ("自定义字段", "Custom fields", r"\bcustom fields\b"),
)


def action_annotations(fact, matrix, zh):
    result = []
    if fact["verification_status"] != "CONFIRMED": return result
    for cn, en, pattern in ACTION_LABELS:
        for eid in fact["evidence_ids"]:
            match = re.search(pattern, matrix["evidence"][eid]["quote"], re.I)
            if match:
                result.append({"label": cn if zh else en, "source_span": match.group(),
                               "fact_id": fact["id"], "evidence_id": eid})
                break
    return result


def categories(fact, matrix):
    if fact["category"] != "FEATURE":
        return []
    name = fact["value"]["feature_name"]
    quotes = " ".join(matrix["evidence"][e]["quote"] for e in fact["evidence_ids"])
    # Require the same category signal in both the feature name and its evidence.
    return [key for key, (_, _, pattern) in CATEGORIES.items()
            if re.search(pattern, name, re.I) and re.search(pattern, quotes, re.I)]


def capability_rows(matrix):
    rows = {}
    selected = {fid for p in matrix["products"] for dim, c in p["cells"].items()
                if dim in {"core_features", "ai_capabilities", "differentiation"} for fid in c["fact_ids"]}
    for fid, fact in matrix["facts"].items():
        if fid not in selected or fact["category"] != "FEATURE":
            continue
        keys = categories(fact, matrix) or ["unmapped:" + fact["value"]["normalized_feature_name"]]
        for key in keys:
            rows.setdefault(key, []).append(fid)
    result = []
    for key, ids in rows.items():
        facts = [matrix["facts"][fid] for fid in ids]
        days = {utc(matrix["evidence"][e]["collected_at"]).date() for f in facts for e in f["evidence_ids"]}
        supported_products = {f["product_id"] for f in facts}
        status = ("SOURCE_CONFLICT" if any(f["verification_status"] != "CONFIRMED" for f in facts)
                  else "TIME_INCOMPARABLE" if len(days) != 1
                  else "AVAILABILITY_UNCERTAIN" if any(f["value"].get("status") in {"COMING_SOON", "DEPRECATED", "BETA"} for f in facts)
                  else "SHARED_CATEGORY" if len(supported_products) == len(matrix["products"]) and len(supported_products) > 1
                  else "ONE_SIDED_EVIDENCE")
        result.append({"category": key, "status": status, "fact_ids": ids,
                       "evidence_ids": sorted({e for f in facts for e in f["evidence_ids"]})})
    return result


def reading_view(task, analysis):
    """Pure JSON view persisted alongside the immutable matrix and source quotes."""
    matrix = analysis["matrix"]
    zh = getattr(task, "output_language", "en") == "zh-CN"
    def tr(cn, en): return cn if zh else en
    labels = {"UNKNOWN": "未知", "CONFIRMED": "已确认", "SOURCE_CONFLICT": "来源冲突", "MONTH": "月", "YEAR": "年",
              "USER": "每用户", "WORKSPACE": "每工作区", "ANNUAL_BILLING": "年付", "MONTHLY_BILLING": "月付",
              "AVAILABLE": "可用", "BETA": "测试版", "COMING_SOON": "尚未发布", "DEPRECATED": "已弃用",
              "core_features": "核心功能", "pricing": "定价", "positioning": "产品定位", "target_users": "目标用户",
              "ai_capabilities": "AI 能力", "differentiation": "差异化"}
    def display(value): return labels.get(str(value), str(value)) if zh else str(value)
    facts, evidence = matrix["facts"], matrix["evidence"]
    references = {eid: str(i + 1) for i, eid in enumerate(evidence)}
    def refs(ids): return " ".join("[" + references[e] + "]" for e in ids)
    def desc(f):
        v = f["value"]
        return v.get("feature_description") or v.get("primary_positioning") or v.get("plan_description") or ""
    def evidence_cell(f):
        annotations = action_annotations(f, matrix, zh) if f["category"] == "FEATURE" else []
        labels = "、".join(a["label"] for a in annotations)
        return (tr("已记录的实现：", "Documented implementation: ") + labels + "。" if labels else "") + desc(f) + " " + refs(f["evidence_ids"])
    states = {"SHARED_CATEGORY": tr("双方均有同类能力证据；实现方式不等同", "Shared category; implementations are not equivalent"),
              "ONE_SIDED_EVIDENCE": tr("仅部分产品有证据，不表示另一方没有", "Evidence on some products only; not proof of absence"),
              "SOURCE_CONFLICT": tr("来源冲突，不能形成比较结论", "Source conflict; comparison withheld"),
              "AVAILABILITY_UNCERTAIN": tr("包含预告、测试版或已弃用功能，不能视为同等可用", "Includes planned, beta or deprecated capabilities; availability is not equivalent"),
              "TIME_INCOMPARABLE": tr("采集时间不可比", "Observation times incomparable")}
    rows = capability_rows(matrix)
    prioritized = {fid for f in analysis.get("conclusions", []) for fid in f["fact_ids"]}
    rows.sort(key=lambda r: (r["status"] != "SHARED_CATEGORY", -len(set(r["fact_ids"]) & prioritized)))
    feature_table = []
    for row in rows:
        key = row["category"]
        label = CATEGORIES[key][0 if zh else 1] if key in CATEGORIES else facts[row["fact_ids"][0]]["value"]["feature_name"]
        cells = []
        for p in matrix["products"]:
            own = [facts[fid] for fid in row["fact_ids"] if facts[fid]["product_id"] == p["product_id"]]
            cells.append("；".join(evidence_cell(f) + tr("；可用状态：", "; availability: ") + display(f["value"].get("status", "UNKNOWN")) for f in own) or tr("信息不足", "Insufficient evidence"))
        feature_table.append([label, *cells, states[row["status"]]])
    shared = [CATEGORIES[r["category"]][0 if zh else 1] for r in rows if r["status"] == "SHARED_CATEGORY" and r["category"] in CATEGORIES]
    summary = tr(f"本次收集 {len(facts)} 条事实，覆盖 {len(matrix['products'])} 个产品。", f"The research contains {len(facts)} facts across {len(matrix['products'])} products.")
    summary += tr("已确认的共同能力类别：", "Evidence-backed shared categories: ") + ("、".join(shared) or tr("尚不足以判断", "not established")) + "。"
    summary += " " + refs(sorted({eid for r in rows if r["status"] == "SHARED_CATEGORY" for eid in r["evidence_ids"]}))
    summary += tr("类别重合不代表功能等价或优劣；本报告不作绝对排名。", "Category overlap does not establish equivalence or superiority; no absolute ranking is made.")
    sections = [{"heading": tr("执行摘要", "Executive summary"), "paragraphs": [summary]},
        {"heading": tr("产品定位与研究范围", "Positioning and research scope"), "paragraphs":
         [tr("原始事实说明保留来源语言；中文标签和分析框架不替代原文证据。", "Source descriptions remain in their original language; presentation labels do not replace evidence.")]
         + [tr("请求维度：", "Requested dimensions: ") + "、".join(display(d) for d in matrix["dimensions"]),
            tr("来源采集时间：", "Source collection times: ") + " / ".join(sorted({e["collected_at"] for e in evidence.values()}))]
         + [f["product"] + "：" + evidence_cell(f) for f in facts.values() if f["category"] == "POSITIONING" and f["verification_status"] == "CONFIRMED"]},
        {"heading": tr("核心功能横向比较", "Capability comparison"),
         "headers": [tr("能力类别", "Category"), *[p["name"] for p in matrix["products"]], tr("比较边界", "Comparison boundary")], "rows": feature_table}]
    pricing = []
    for p in matrix["products"]:
        own = [f for f in facts.values() if f["product_id"] == p["product_id"] and f["category"] in {"PLAN", "PRICE"}]
        if not own:
            pricing.append([p["name"], "—", tr("信息不足", "Insufficient evidence"), "—"])
        for f in own:
            v = f["value"]
            if f["category"] == "PRICE":
                fields = [("amount", "金额"), ("currency", "币种"), ("billing_unit", "单位"), ("billing_period", "周期"),
                          ("billing_commitment", "付费承诺"), ("region", "地区"), ("tax_status", "税费")]
                detail = "；".join((cn if zh else k) + ": " + display(v.get(k) if v.get(k) is not None else tr("未知", "unknown")) for k, cn in fields)
            else:
                detail = tr("套餐权益（原文）：", "Plan entitlements (source text): ") + "; ".join(v.get("included_features", []))
            pricing.append([p["name"], v["plan_name"], detail, display(f["verification_status"]) + " " + refs(f["evidence_ids"])])
    sections.append({"heading": tr("定价与套餐对比", "Pricing and plans"), "headers": [tr("产品", "Product"), tr("套餐", "Plan"), tr("已确认信息", "Observed information"), tr("证据", "Evidence")], "rows": pricing,
                     "paragraphs": [tr("展示金额不等于可比价格。币种、单位、周期、付费承诺、地区和税费须均有可比证据；否则不作更便宜的判断。", "Displayed amounts are not automatically comparable prices. Currency, unit, period, commitment, region and tax basis must be supported before a lower-price claim.")]})
    # Deterministic analysis planning: explain which supported contrasts can inform
    # evaluation without inventing translations, suitability or absent capabilities.
    contrasts = []
    for r in rows:
        if r["status"] != "SHARED_CATEGORY": continue
        supported = [facts[fid] for fid in r["fact_ids"]]
        label = CATEGORIES.get(r["category"], (r["category"], r["category"]))[0 if zh else 1]
        contrasts.append(tr("分析推断：", "Analysis inference: ") + label + tr("应按具体实现评估，而非仅按有无打勾。已记录的实现分别为：", "should be evaluated by implementation, not a presence checkbox. Documented implementations: ")
                         + "；".join(f["product"] + " — " + evidence_cell(f) for f in supported)
                         + tr("这些描述支持比较实现侧重点，但不证明排他性、性能差距或用户适配优劣。", "These descriptions support examining implementation emphasis, not exclusivity, performance gaps or suitability rankings."))
    sections.append({"heading": tr("竞争差异与场景分析", "Competitive differences and scenarios"), "paragraphs": contrasts or [tr("可比证据不足，暂不形成场景优劣判断。", "Comparable evidence is insufficient for scenario recommendations.")]})
    sections.append({"heading": tr("综合结论", "Conclusions"), "paragraphs": [
        tr("现有证据可支持按实现方式进一步评估上述共同能力；单方证据应作为待核查项，不能直接当作独有优势。", "The evidence supports evaluating shared categories by implementation. One-sided evidence identifies verification work, not exclusive advantages."),
        tr("成本判断须满足定价可比条件；功能证据覆盖度不等于产品能力覆盖度。", "Cost judgments require comparable pricing evidence; research coverage is not product capability coverage."),
        tr("模型综合状态：", "Model synthesis status: ") + analysis["synthesis_status"]]})
    gaps = matrix["gaps"] + analysis["limitations"] + analysis["issues"]
    gap_labels = {
        "INFORMATION_INSUFFICIENT": tr("缺少确认事实，不能据此判断产品没有该能力", "No confirmed facts; absence cannot be inferred"),
        "FACT_EXTRACTION_PARTIAL": tr("部分候选事实未通过提取或证据校验", "Some candidates did not pass extraction or evidence validation"),
        "PRODUCT_RESEARCH_PARTIAL": tr("产品研究仅部分完成", "Product research is partial"),
        "NO_COMPLETENESS_OR_SUITABILITY_RANKING": tr("缺少完整覆盖与用户需求证据，不作全面性或适用性排名", "No completeness or suitability rankings without coverage and user requirements"),
        "PRICE_BASIS_UNKNOWN": tr("定价口径缺失，不能比较高低", "Missing price basis; prices cannot be ranked"),
        "SOURCE_CONFLICT": tr("来源存在冲突", "Conflicting sources"),
        "OBSERVATION_TIME_INCOMPARABLE": tr("观察时间不可比", "Incomparable observation times"),
        "SYNTHESIS_FAILED": tr("模型综合失败；仅保留规则约束的证据对照", "Model synthesis failed; only rule-bound evidence comparisons remain"),
        "TASK_BUDGET_EXHAUSTED": tr("任务预算耗尽，研究不完整", "Task budget exhausted; research incomplete"),
    }
    gap_text = []
    for gap in gaps:
        code = gap if isinstance(gap, str) else gap.get("code", "UNKNOWN")
        scope = "" if isinstance(gap, str) else " / ".join(display(gap[k]) for k in ("product", "dimension") if gap.get(k))
        gap_text.append(scope + "：" + gap_labels.get(code, code))
    sections.append({"heading": tr("研究局限", "Research limitations"), "paragraphs":
        ([tr("部分报告：信息缺口未解决，不代表已完成全部研究。", "Partial report: unresolved gaps remain; research is not complete.")] if analysis["status"] != "COMPLETE" else []) + gap_text})
    return {"version": "competitive-reading-v1", "language": "zh-CN" if zh else "en",
            "title": tr("竞品分析：", "Competitive analysis: ") + " / ".join(p["name"] for p in matrix["products"]),
            "status": analysis["status"], "executive_summary": summary, "sections": sections,
            "capabilities": rows, "gaps": gaps,
            "annotations": [a for f in facts.values() if f["category"] == "FEATURE" for a in action_annotations(f, matrix, zh)],
            "references": [{"label": references[eid], **e} for eid, e in evidence.items()]}

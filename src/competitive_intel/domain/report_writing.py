"""Offline writing from verified facts; free-form model assertions are not trusted.

Rules translate bounded spans in BOTH confirmed fact fields and their evidence.
This is a finite editorial vocabulary, not a general translator or entailment model.
Unknown wording remains available in the source/audit, never guessed in Chinese.
"""

from copy import deepcopy
from hashlib import sha256
import json
import re
from urllib.parse import urlsplit

from .competitive_matrix import utc
from .comparison_presentation import CATEGORIES, capability_rows, action_annotations
from .competitive_findings import build_findings, price_comparability


# Product-independent concepts: key, source expression, Chinese, English, workflow.
RULES = (
    ("agents", r"\bAI agents?\b", "AI 智能体", "AI agents", "agents"),
    ("delegate", r"\bdelegate entire issues\b", "完整事项委派", "delegating entire issues", "execution"),
    ("ideas", r"\bbrainstorm new ideas\b", "辅助创意构思", "idea brainstorming", "preparation"),
    ("actions", r"\borganize action items\b", "整理行动事项", "organizing action items", "preparation"),
    ("condense", r"\bcondense lengthy texts\b", "精简长文本", "condensing long texts", "preparation"),
    ("rules", r"\b(?:set )?automated rules\b", "设置自动化规则", "configuring automation rules", "rules"),
    ("commands", r"\brun commands\b", "执行命令", "running commands", "rules"),
    ("intake", r"\bturn conversations and customer feedback into actionable issues\b", "将对话和客户反馈转为可处理事项", "turning conversations and feedback into issues", "intake"),
    ("routing", r"\brouted, labeled, and prioritized\b", "对事项分派、标记并确定优先级", "routing, labeling and prioritizing issues", "intake"),
    ("apps", r"\b(?:integrate|connect)\b[^.!?\n]{0,80}\bapps and services\b", "连接应用与服务", "connecting apps and services", "connection"),
    ("sync", r"\bsync and manage your tasks\b", "同步并管理任务", "syncing and managing tasks", "connection"),
    ("roadmap", r"\b(?:strategic )?roadmaps?\b", "路线图规划", "roadmap planning", "planning"),
    ("prd", r"\bPRDs\b", "产品需求文档", "product requirements documents", "planning"),
    ("review", r"\bcode reviews?\b", "代码审查", "code reviews", "delivery"),
    ("split", r"\bbreak big tasks into small ones\b", "将大任务拆成小任务", "breaking large tasks into smaller tasks", "tracking"),
    ("due", r"\bdue dates?\b", "截止日期", "due dates", "tracking"),
    ("fields", r"\bcustom fields\b", "自定义字段", "custom fields", "tracking"),
    ("attachments", r"\battachments?\b", "附件", "attachments", "tracking"),
    ("product_system", r"\bproduct development system\b", "产品开发系统", "product development system", "positioning"),
    ("work_tool", r"\bwork management tool\b", "工作管理工具", "work management tool", "positioning"),
    ("planning_products", r"\bplanning and building products\b", "产品规划与开发", "planning and building products", "positioning"),
    ("ideate", r"\bideate plans\b", "构思计划", "ideating plans", "positioning"),
    ("collaborate", r"\bcollaborate on projects\b", "项目协作", "project collaboration", "positioning"),
    ("workflows", r"\borganize workflows\b", "组织工作流程", "organizing workflows", "positioning"),
    ("progress", r"\btrack progress\b", "跟踪进度", "tracking progress", "positioning"),
)
WORKFLOWS = {
    "execution": ("任务执行与委派", "task execution and delegation"),
    "preparation": ("内容准备与整理", "content preparation"),
    "rules": ("规则配置与命令执行", "rule configuration and commands"),
    "intake": ("需求与反馈入口", "requirements and feedback intake"),
    "connection": ("外部工具连接与任务衔接", "external tools and task coordination"),
    "planning": ("项目规划", "project planning"),
    "delivery": ("开发交付", "development delivery"),
    "tracking": ("任务组织与跟踪", "task organization and tracking"),
}
NEGATION = re.compile(r"\b(?:not|never|cannot|can't|without|unsupported|no longer)\b|不支持|无法|尚未", re.I)


def denied_span(text, match):
    """Conservatively reject negation in the matched sentence, not other claims."""
    start = max(text.rfind(c, 0, match.start()) for c in ".!?\n") + 1
    ends = [text.find(c, match.end()) for c in ".!?\n"]
    end = min((n for n in ends if n >= 0), default=len(text))
    return bool(NEGATION.search(text[start:end]))


def validate_support(matrix, fact_ids):
    """Validate links and provenance metadata, not just existence of an ID.

The matrix must originate from build_matrix's repository evidence recheck.
This additional gate does not replace original quotation/identity validation.
"""
    evidence_ids = set()
    for fid in fact_ids:
        f = matrix["facts"].get(fid)
        if not f or f["id"] != fid or f["verification_status"] != "CONFIRMED" or not f["evidence_ids"]:
            raise ValueError("WRITING_UNCONFIRMED_FACT")
        for eid in f["evidence_ids"]:
            e = matrix["evidence"].get(eid)
            if (not e or e.get("id") != eid or e.get("product_id") != f["product_id"]
                    or e.get("verification_status") != "CONFIRMED" or not e.get("quote")
                    or not isinstance(e.get("confidence"), (float, int)) or isinstance(e["confidence"], bool)
                    or not 0 <= e["confidence"] <= 1):
                raise ValueError("WRITING_INVALID_EVIDENCE")
            url = urlsplit(e.get("url", ""))
            if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
                raise ValueError("WRITING_INVALID_SOURCE_URL")
            utc(e.get("collected_at"))
            evidence_ids.add(eid)
    return sorted(evidence_ids)


def fact_phrases(fact, matrix, zh):
    """Each phrase has an exact field span and quote span. No raw-quote mining."""
    fields = ("feature_description",) if fact["category"] == "FEATURE" else ("primary_positioning", "public_description")
    result = []
    for key, pattern, cn, en, workflow in RULES:
        for field in fields:
            value = fact["value"].get(field, "")
            match = re.search(pattern, value, re.I)
            if not match or denied_span(value, match):
                continue
            for eid in fact["evidence_ids"]:
                quote = matrix["evidence"][eid]["quote"]
                source = re.search(pattern, quote, re.I)
                if source and not denied_span(quote, source):
                    result.append(dict(rule=key, text=cn if zh else en, workflow=workflow,
                                       field=field, field_span=match.group(), source_span=source.group(),
                                       fact_id=fact["id"], evidence_id=eid))
                    break
            if result and result[-1]["rule"] == key:
                break
    return result


def plan_term(value):
    """Finite translation of entitlements; retain unknown named terms verbatim."""
    terms = {"Admin roles": "管理员角色", "Private teams and guests": "私有团队及访客",
             "Agent platform": "智能体平台"}
    if value in terms:
        return terms[value]
    integration = re.fullmatch(r"([A-Z][A-Za-z0-9]+) and ([A-Z][A-Za-z0-9]+) integrations", value)
    if integration:
        return "与 " + "、".join(integration.groups()) + " 的集成"
    units = {"teams": "团队", "issues": "事项", "members": "成员", "file uploads": "文件上传"}
    match = re.fullmatch(r"(Unlimited|\d+) (teams|issues|members|file uploads)", value, re.I)
    if match:
        count, unit = match.groups()
        return units[unit.lower()] + ("数量不限" if count.lower() == "unlimited" else "：" + count)
    # Named product/integration terms remain exact, not translated by guesswork.
    return value


def build_reading_document(task, analysis):
    matrix = analysis["matrix"]
    zh = getattr(task, "output_language", "en") == "zh-CN"
    def tr(cn, en): return cn if zh else en
    facts = matrix["facts"]
    confirmed = {fid: f for fid, f in facts.items() if f["verification_status"] == "CONFIRMED"}
    validate_support(matrix, confirmed)
    refs = {eid: str(i + 1) for i, eid in enumerate(matrix["evidence"])}
    statements, sections, phrases = [], [], {}
    findings = build_findings(matrix)["findings"]
    for fid, f in confirmed.items():
        phrases[fid] = fact_phrases(f, matrix, zh) if f["category"] in {"FEATURE", "POSITIONING"} else []

    def say(text, kind="POLICY", ids=(), finding_ids=()):
        if not zh:
            text = text.replace("；", "; ").replace("。", ".").replace("：", ": ").replace("、", ", ")
        ids = sorted(set(ids))
        eids = validate_support(matrix, ids)
        if kind in {"FACT", "ANALYSIS_INFERENCE"} and not ids:
            raise ValueError("WRITING_MISSING_SUPPORT")
        statement = dict(id=f"claim-{len(statements)+1}", kind=kind, text=text,
                         fact_ids=ids, evidence_ids=eids, finding_ids=list(finding_ids))
        statements.append(statement)
        return text + (" " + " ".join(f"[{refs[e]}]" for e in eids) if eids else "")

    def section(cn, en, paragraphs=(), **table):
        sections.append(dict(heading=tr(cn, en), paragraphs=list(paragraphs), **table))

    rows = capability_rows(matrix)
    # Existing synthesis may prioritize known comparison facts, never supply prose.
    allowed = {(f["kind"], tuple(sorted(f["fact_ids"]))) for f in findings}
    prioritized = {fid for f in analysis.get("conclusions", [])
                   if (f.get("kind"), tuple(sorted(f.get("fact_ids", [])))) in allowed
                   for fid in f["fact_ids"]}
    rows.sort(key=lambda r: (r["status"] != "SHARED_CATEGORY", -len(set(r["fact_ids"]) & prioritized)))
    shared = [r for r in rows if r["status"] == "SHARED_CATEGORY"]
    shared_ids = sorted({fid for r in shared for fid in r["fact_ids"]})
    shared_names = [CATEGORIES[r["category"]][0 if zh else 1] for r in shared if r["category"] in CATEGORIES]
    scope = say(tr(f"本报告比较 {len(matrix['products'])} 个产品，以 {len(confirmed)} 条已确认事实为依据。",
                   f"This report compares {len(matrix['products'])} products using {len(confirmed)} confirmed facts."), "RESEARCH_SCOPE")
    summary = [scope]
    if shared_ids:
        summary.append(say(tr("共同能力覆盖：" + "、".join(shared_names) + "。比较重点是这些能力进入工作流程的方式，而非功能数量。",
                              "Shared categories include " + ", ".join(shared_names) + "; the useful comparison concerns workflow implementation, not feature counts."), "ANALYSIS_INFERENCE", shared_ids))
    missing_prices = [p["name"] for p in matrix["products"] if not any(f["product_id"] == p["product_id"] and f["category"] == "PRICE" for f in confirmed.values())]
    if missing_prices:
        summary.append(say(tr("、".join(missing_prices) + " 尚缺确认的结构化价格，成本结论需待补证。",
                              ", ".join(missing_prices) + " lack confirmed structured prices; cost conclusions remain open."), "INFORMATION_GAP"))
    if analysis["status"] != "COMPLETE":
        summary.append(say(tr("本次研究为部分报告，结论仅覆盖已取得的证据。", "This is a partial report; conclusions cover only the collected evidence."), "INFORMATION_GAP"))
    section("执行摘要", "Executive summary", summary)

    positioning = []
    for fid, f in confirmed.items():
        if f["category"] != "POSITIONING": continue
        if zh:
            labels = [p["text"] for p in phrases[fid]]
            types = [p["text"] for p in phrases[fid] if p["rule"] in {"product_system", "work_tool"}]
            uses = [label for label in labels if label not in types]
            text = ("定位为" + "、".join(types) if types else "官方描述") + ("，强调" + "、".join(uses) if uses else "") if labels else "已取得官方定位说明，当前离线词表无法完整转述，请查看来源原文"
            text = f["product"] + " " + text
        else:
            text = f["product"] + ": official positioning describes " + f["value"]["primary_positioning"]
        positioning.append(say(text + "。", "FACT", [fid]))
    dimension_names = {"core_features": "核心功能", "pricing": "定价", "positioning": "产品定位", "target_users": "目标用户", "ai_capabilities": "AI 能力", "differentiation": "竞争差异"}
    scope_text = say(tr("请求范围：", "Requested scope: ") + "、".join(dimension_names.get(d, d) if zh else d.replace("_", " ") for d in matrix["dimensions"]), "RESEARCH_SCOPE")
    section("产品定位与研究范围", "Positioning and research scope", [scope_text] + (positioning or [say(tr("尚缺经验证的官方定位说明。", "Verified positioning evidence is missing."), "INFORMATION_GAP")]))

    states = {
        "SHARED_CATEGORY": tr("同类能力，需结合实现方式比较", "Shared category; compare implementations"),
        "ONE_SIDED_EVIDENCE": tr("对照证据尚不齐全", "Counterpart evidence is incomplete"),
        "SOURCE_CONFLICT": tr("来源有冲突，暂缓判断", "Conflicting sources; judgment withheld"),
        "TIME_INCOMPARABLE": tr("采集日期不同，暂缓比较", "Different observation dates; comparison withheld"),
        "AVAILABILITY_UNCERTAIN": tr("包含测试、预告或已弃用功能", "Includes beta, planned or deprecated features"),
    }
    table = []
    for r in rows:
        label = CATEGORIES[r["category"]][0 if zh else 1] if r["category"] in CATEGORIES else tr("其他功能", "Other features")
        cells = []
        for product in matrix["products"]:
            own = [fid for fid in r["fact_ids"] if fid in confirmed and facts[fid]["product_id"] == product["product_id"]]
            texts = []
            for fid in own:
                f = facts[fid]
                if zh:
                    text = "、".join(p["text"] for p in phrases[fid]) or "已取得功能说明，详细内容请查阅来源原文"
                else:
                    text = f["value"]["feature_description"]
                status = f["value"].get("status", "UNKNOWN")
                if status in {"BETA", "COMING_SOON", "DEPRECATED"}:
                    text += "（" + ({"BETA": "测试版", "COMING_SOON": "预告功能", "DEPRECATED": "已弃用"}[status] if zh else status) + "）"
                texts.append(say(text, "FACT", [fid]))
            cells.append(tr("；", "; ").join(texts) or say(tr("尚待补充证据", "Evidence still needed"), "INFORMATION_GAP"))
        table.append([label, *cells, states[r["status"]]])
    section("核心功能横向比较", "Capability comparison", [say(tr("下表概述官方材料中已验证的功能描述。未列明发布状态或套餐范围的功能，仍需核查实际开放条件；空缺表示本次研究未取得充分证据。", "The matrix summarizes verified official descriptions. Release status and plan eligibility still need checking where unspecified; gaps describe research coverage."))],
            headers=[tr("能力类别", "Category"), *[p["name"] for p in matrix["products"]], tr("比较边界", "Comparison boundary")], rows=table)

    pricing = []
    price_facts = [f for f in confirmed.values() if f["category"] == "PRICE"]
    for product in matrix["products"]:
        own = [f for f in confirmed.values() if f["product_id"] == product["product_id"] and f["category"] in {"PLAN", "PRICE"}]
        if not own:
            pricing.append([product["name"], "—", say(tr("尚无确认的价格及套餐信息", "No confirmed price or plan information"), "INFORMATION_GAP")])
        for f in own:
            v = f["value"]
            if f["category"] == "PLAN":
                terms = [plan_term(x) if zh else x for x in v.get("included_features", [])]
                detail = tr("权益：", "Entitlements: ") + "；".join(terms)
                if not any(p["product_id"] == f["product_id"] and p["value"]["plan_name"] == v["plan_name"] for p in price_facts):
                    detail += tr("。该套餐尚缺确认的结构化价格。", ". A confirmed structured price for this plan is missing.")
            else:
                labels = {"UNKNOWN": "未明确", "USER": "每用户", "WORKSPACE": "每工作区", "MONTH": "月", "YEAR": "年", "ANNUAL_BILLING": "年付", "MONTHLY_BILLING": "月付"}
                fields = (("amount", "金额"), ("currency", "币种"), ("billing_unit", "计费单位"), ("billing_period", "计费周期"), ("billing_commitment", "付费条件"), ("region", "地区"), ("tax_status", "税费"))
                detail = "；".join((cn if zh else key) + "：" + (labels.get(str(v.get(key) or "UNKNOWN"), str(v.get(key))) if zh else str(v.get(key) or "unknown")) for key, cn in fields)
            pricing.append([product["name"], v["plan_name"], say(detail, "FACT", [f["id"]])])
    price_notes = [say(tr("网页上的金额、已验证的结构化价格与可比价格是三个不同层次。只有币种、计费单位、周期、付费条件、地区、税费及采集时间均可对齐时，才比较单位价格；套餐权益和总成本仍须另行评估。", "Displayed amounts, verified structured prices and comparable prices are distinct. Compare unit prices only when currency, unit, period, commitment, region, tax and observation time align; entitlements and total cost require separate evaluation."))]
    for i, left in enumerate(price_facts):
        for right in price_facts[i+1:]:
            if left["product_id"] == right["product_id"]: continue
            if price_comparability(left, right, matrix):
                price_notes.append(say(tr("这组价格缺少一致的比较口径，暂不比较高低。", "These prices do not share a verified comparison basis; no ranking is made."), "ANALYSIS_INFERENCE", [left["id"], right["id"]]))
    section("定价与套餐", "Pricing and plans", price_notes, headers=[tr("产品", "Product"), tr("套餐", "Plan"), tr("已确认信息与缺口", "Confirmed information and gaps")], rows=pricing)

    # Merge shared categories connected by the same fact, avoiding AI/automation
    # reusing the same implementation in several narrative paragraphs.
    groups = []
    for r in shared:
        ids = set(r["fact_ids"])
        touching = [g for g in groups if ids & g]
        for g in touching:
            ids |= g
            groups.remove(g)
        groups.append(ids)
    contrasts, contrast_ids = [], []
    for ids in groups:
        focuses = []
        signatures = []
        for product in matrix["products"]:
            workflows = sorted({p["workflow"] for fid in ids if facts[fid]["product_id"] == product["product_id"] for p in phrases[fid] if p["workflow"] in WORKFLOWS})
            signatures.append(tuple(workflows))
            if workflows:
                focuses.append(product["name"] + tr(" 的材料侧重", " documents ") + "、".join(WORKFLOWS[w][0 if zh else 1] for w in workflows))
        if len(focuses) != len(matrix["products"]) or len(set(signatures)) < 2:
            continue
        linked = [f["id"] for f in findings if f["kind"] == "SHARED_CAPABILITY_IMPLEMENTATIONS" and set(f["fact_ids"]) <= ids]
        workflow_set = {w for signature in signatures for w in signature}
        if workflow_set & {"intake", "connection"}:
            implication = tr("。这提示集成评估需要分别检查信息如何进入任务流程，以及任务如何在工具之间衔接；连接数量本身不足以说明流程是否连贯。", ". Integration evaluation should examine both information intake and task coordination across tools; connector counts alone do not establish workflow continuity.")
        else:
            implication = tr("。这些环节对应不同的工作目标。若关注自动化带来的价值，应以同一任务验证从内容准备到执行完成的全过程，不能把文本辅助直接等同于端到端执行。", ". These workflow steps address different goals. To evaluate automation value, test the same task from preparation through completion; text assistance is not equivalent to end-to-end execution.")
        contrasts.append(say(tr("分析推断：", "Analysis inference: ") + "；".join(focuses) + implication, "ANALYSIS_INFERENCE", ids, linked))
        contrast_ids.append(statements[-1]["id"])
    if contrasts:
        contrasts.append(say(tr("上述判断解释的是官方材料呈现的侧重点，尚未验证实际完成质量、人工介入程度或适用人群，不能据此排列产品优劣。", "These inferences concern documented emphasis. Outcome quality, human intervention and user suitability have not been verified; no superiority ranking follows.")))
        contrast_fact_ids = {fid for claim in statements if claim["id"] in contrast_ids for fid in claim["fact_ids"]}
        summary.insert(2, say(tr("已证实的实现描述呈现出不同的工作流程侧重点，同类能力之间是否能够相互替代，仍需在具体任务中验证。", "Verified implementation descriptions emphasize different workflow steps; substitutability within a shared category still requires task-level evaluation."), "ANALYSIS_INFERENCE", contrast_fact_ids))
        sections[0]["paragraphs"] = list(summary)
    section("竞争差异分析", "Competitive differences", contrasts or [say(tr("现有材料尚不足以形成有区分度的跨产品工作流程判断。", "Evidence is insufficient for a distinct cross-product workflow interpretation."), "INFORMATION_GAP")])

    questions = [say(tr("后续核查应使用同一组真实任务，记录完成结果、所需人工步骤和限制条件。只有需求条件与对照结果都明确后，才能形成用户适配或竞争优势判断。", "Evaluate the same real tasks and record outcomes, manual steps and constraints. Suitability or competitive advantage requires explicit requirements and comparable results."), "FOLLOW_UP")]
    one_sided = [r for r in rows if r["status"] == "ONE_SIDED_EVIDENCE"]
    if one_sided:
        questions.append(say(tr(f"另有 {len(one_sided)} 类功能的对照材料尚不齐全，建议先补齐对方的同类官方说明，再判断是否存在实质差异。", f"Counterpart documentation is incomplete for {len(one_sided)} categories. Obtain equivalent official descriptions before treating them as differentiators."), "INFORMATION_GAP"))
    unpriced_plans = [f["product"] + " " + f["value"]["plan_name"] for f in confirmed.values() if f["category"] == "PLAN" and not any(p["product_id"] == f["product_id"] and p["value"]["plan_name"] == f["value"]["plan_name"] for p in price_facts)]
    if unpriced_plans or missing_prices:
        questions.append(say(tr("成本核查的优先项：补齐", "Cost verification priorities: obtain structured prices for ") + "、".join(unpriced_plans + missing_prices) + tr("的结构化报价及计费条件，再按同一使用规模核算；目前无法给出可靠的价格排序。", " and their billing conditions, then compare at the same usage scale. A reliable price ranking is not yet possible."), "INFORMATION_GAP"))
    else:
        questions.append(say(tr("预算决策还需要将候选套餐与目标使用规模、功能权益逐项对齐。", "Budget decisions still require matching candidate plans to expected scale and entitlements."), "FOLLOW_UP"))
    section("综合结论与后续核查", "Conclusions and next checks", questions)

    gaps = deepcopy(matrix["gaps"] + analysis["limitations"] + analysis["issues"])
    limits = [say(tr("本报告区分官方事实说明、规则约束的分析推断和待核查问题。功能描述不等于实际使用效果；单方材料也不足以证明独有优势。", "This report distinguishes official descriptions, rule-bound inferences and follow-up questions. Descriptions do not establish outcomes; one-sided documentation does not prove exclusivity.")),
              say(tr("中文采用有限的、可核对原文片段的表达规则，无法覆盖所有来源措辞；未覆盖的细节保留在引用和审计区。本轮未使用真实写作模型。", "Chinese wording uses finite, auditable span rules; uncovered detail remains in quotations and audit data. No live writing model was used."))]
    if analysis["status"] != "COMPLETE":
        limits.insert(0, say(tr("部分报告：仍有研究或比较缺口，不能视为完整评估。", "Partial report: research or comparison gaps remain."), "INFORMATION_GAP"))
    gap_labels = {
        "FACT_EXTRACTION_PARTIAL": ("部分候选事实未通过提取或引用验证", "some candidate facts did not pass extraction or quotation validation"),
        "PRODUCT_RESEARCH_PARTIAL": ("产品研究尚未完整完成", "product research remains partial"),
        "INFORMATION_INSUFFICIENT": ("尚缺足够的确认事实", "confirmed evidence is insufficient"),
        "SOURCE_CONFLICT": ("来源存在冲突，相关内容不能作为确认结论", "conflicting sources prevent confirmation"),
        "OBSERVATION_TIME_INCOMPARABLE": ("采集日期不同，不能直接比较", "different observation dates prevent direct comparison"),
        "SYNTHESIS_FAILED": ("综合分析步骤失败，当前保留的是规则约束的比较", "synthesis failed; rule-bound comparisons are retained"),
        "TASK_BUDGET_EXHAUSTED": ("研究预算耗尽，仍有未完成项", "research budget exhausted with work outstanding"),
    }
    seen_gaps = set()
    for gap in gaps:
        code = gap if isinstance(gap, str) else gap.get("code", "UNKNOWN")
        if code == "NO_COMPLETENESS_OR_SUITABILITY_RANKING": continue
        scope = "" if isinstance(gap, str) else " / ".join(dimension_names.get(gap[k], gap[k]) if zh else gap[k] for k in ("product", "dimension") if gap.get(k))
        label = gap_labels.get(code, ("存在尚待核查的研究或比较限制，详情见审计区", "an unresolved research or comparison limitation remains; see audit details"))[0 if zh else 1]
        text = (scope + "：" if scope else "") + label + "。"
        if text not in seen_gaps:
            limits.append(say(text, "INFORMATION_GAP"))
            seen_gaps.add(text)
    section("证据来源与研究局限", "Evidence and research limitations", limits)
    return dict(version="competitive-reading-v2", language="zh-CN" if zh else "en", status=analysis["status"],
                title=tr("竞品分析：", "Competitive analysis: ") + " / ".join(p["name"] for p in matrix["products"]),
                executive_summary="\n".join(summary), sections=sections, capabilities=rows, gaps=gaps,
                references=[dict(label=refs[eid], **e) for eid, e in matrix["evidence"].items()],
                annotations=[a for f in confirmed.values() if f["category"] == "FEATURE" for a in action_annotations(f, matrix, zh)],
                writing=dict(policy="evidence-writing-v1", status="OFFLINE_RULES", claims=statements,
                             editable_claim_ids=contrast_ids, phrases=[p for ps in phrases.values() for p in ps],
                             findings=findings, synthesis_status=analysis["synthesis_status"]))


def writing_request(view):
    """Transport-independent mock/adapter contract. No live adapter is registered."""
    claims = [c for c in view["writing"]["claims"] if c["id"] in view["writing"]["editable_claim_ids"]]
    return dict(language=view["language"], policy="Reorder supplied claims only; do not author assertions.", claims=deepcopy(claims),
                document_hash=sha256(json.dumps(view, sort_keys=True, ensure_ascii=False).encode()).hexdigest())


def validate_writing(payload, request):
    """Valid citations alone never authorize prose. Require server-authored claims.

An arbitrary paraphrase is rejected even if a model asserts it is grounded.
This deliberately limits fluency until a separate semantic review is available.
"""
    if not isinstance(payload, dict) or set(payload) != {"document_hash", "claims"} or payload["document_hash"] != request["document_hash"]:
        raise ValueError("WRITING_INVALID_SCHEMA")
    claims = payload["claims"]
    known = {c["id"]: c for c in request["claims"]}
    if not isinstance(claims, list) or len(claims) != len(known):
        raise ValueError("WRITING_INCOMPLETE")
    seen = set()
    for claim in claims:
        if not isinstance(claim, dict) or not isinstance(claim.get("id"), str):
            raise ValueError("WRITING_INVALID_CLAIM")
        cid = claim["id"]
        if cid in seen or cid not in known or claim != known[cid]:
            raise ValueError("WRITING_UNSUPPORTED_CLAIM")
        seen.add(cid)
    return deepcopy(claims)


def apply_writing_provider(view, provider):
    """Optional dependency-injected editor; failure keeps the deterministic report."""
    result = deepcopy(view)
    request = writing_request(view)
    try:
        claims = validate_writing(provider.write(deepcopy(request)), request)
    except Exception:
        result["writing"]["status"] = "REJECTED_EDITOR_OUTPUT"
        return result
    if claims:
        by_id = {c["id"]: c for c in view["writing"]["claims"]}
        original = view["sections"][4]["paragraphs"][:len(claims)]
        rendered = dict(zip(view["writing"]["editable_claim_ids"], original, strict=True))
        result["sections"][4]["paragraphs"] = [rendered[c["id"]] for c in claims] + view["sections"][4]["paragraphs"][len(claims):]
        result["writing"]["editor_order"] = [by_id[c["id"]]["id"] for c in claims]
    result["writing"]["status"] = "VALIDATED_EDITOR_ORDER"
    return result

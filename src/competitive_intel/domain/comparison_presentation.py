"""Evidence-bound capability grouping and entry point for the reading document.

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
    """Build the shared reading document without provider calls."""
    from .report_writing import build_reading_document
    return build_reading_document(task, analysis)

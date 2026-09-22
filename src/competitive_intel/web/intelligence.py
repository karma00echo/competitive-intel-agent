"""Deterministic, allow-listed product projections; no persistence or analysis."""

from urllib.parse import urlsplit, urlunsplit

from .display import FactDisplayFormatter, decode_json


def public_url(value):
    """Evidence links do not expose userinfo, query credentials, or fragments."""
    try:
        parts = urlsplit(value or "")
        if parts.scheme not in {"http", "https"} or not parts.hostname:
            return None
        host = parts.hostname
        if ":" in host:
            host = f"[{host}]"
        if parts.port:
            host += f":{parts.port}"
        return urlunsplit((parts.scheme, host, parts.path, "", ""))
    except ValueError:
        return None


class SignalPresenter:
    CATEGORIES = {"PRICE": "Pricing", "PLAN": "Pricing", "FEATURE": "Feature",
                  "PRODUCT_UPDATE": "Product", "POSITIONING": "Positioning",
                  "WEBSITE": "Website", "SOURCE": "Source"}

    @classmethod
    def present(cls, row):
        category = row["fact_key"].split(".", 1)[0].upper()
        old, new = FactDisplayFormatter().format_change(
            category, row["fact_key"], row["old_value"], row["new_value"])
        kind = "UNCOMPARABLE" if row["change_type"] == "UNKNOWN" else row["change_type"]
        value = decode_json(row["new_value"]) or decode_json(row["old_value"])
        label = ""
        if isinstance(value, dict):
            label = value.get("plan_name") or value.get("feature_name") or value.get("update_title") or ""
        verb = {"ADDED": "added", "MODIFIED": "changed", "REMOVED": "removed", "UNCOMPARABLE": "requires review", "UNCHANGED": "unchanged"}[kind]
        return {
            "signal_id": row["id"], "competitor_id": row["competitor_id"],
            "competitor": row["name"], "run_id": row["run_id"],
            "category": cls.CATEGORIES.get(category, "Other"), "change_type": kind,
            "summary": f"{label + ' · ' if label else ''}{cls.CATEGORIES.get(category, 'Other')} {verb}"[:300],
            "old_value": old[:1000], "new_value": new[:1000],
            "detected_at": row["created_at"],
            "evidence_excerpt": (row.get("evidence_text") or "")[:500],
            "source_url": public_url(row.get("source_url")),
            "status": "needs_review" if kind == "UNCOMPARABLE" or row["verification_status"] != "CONFIRMED" else "confirmed",
        }


class CommandCenterPresenter:
    @staticmethod
    def card(row):
        reasons = []
        if row["run_status"] == "FAILED":
            reasons.append("Latest analysis failed")
        if row["has_warnings"]:
            reasons.append("Latest analysis completed with warnings")
        if not row["verified_source_count"]:
            reasons.append("No verified official source")
        if row["pending_source_count"]:
            reasons.append("Official source verification pending")
        if row["unknown_count"]:
            reasons.append("Latest changes could not be compared")
        if row["missing_report"]:
            reasons.append("Latest completed analysis has no generated report")
        return {
            "competitor_id": row["competitor_id"], "name": row["name"],
            "official_domain": row["official_domain"], "last_checked": row["last_checked"],
            "last_attempt": row["started_at"], "run_id": row["run_id"],
            "status": "Needs attention" if reasons else ("In progress" if row["run_status"] == "RUNNING" else "Last check completed"),
            "warnings": reasons, "verified_source_count": row["verified_source_count"],
            "signals_30d": row["signal_count"], "report_id": row["report_id"],
        }


class CompetitorProfilePresenter:
    @staticmethod
    def fact(row):
        return {"fact_id": row["id"], "category": row["fact_category"],
                "display_value": FactDisplayFormatter().format(row["fact_category"], row["normalized_value"], fact_key=row["fact_key"], value_text=row.get("value_text"))[:1000],
                "evidence_excerpt": row["evidence_text"][:500],
                "source_url": public_url(row["source_url"]),
                "confidence": float(row["confidence"]), "collected_at": row["valid_from"]}


def parse_analyst_command(text):
    """Grammar only: dispatch to existing APIs, never an open-ended model."""
    import re
    text = text.strip().rstrip("。！？!?")
    if text in {"最近有哪些变化", "查看最近 signals"}:
        return {"action": "signals"}
    if re.fullmatch(r"为什么本次没有提取事实[？?]?", text):
        return {"action": "capability"}
    # Deliberately bounded grammar, shared by Analyst and the chat homepage.
    if re.search(r"比较|对比|预测|随便|聊聊|compare|predict", text, re.I):
        return {"action": "unsupported", "message": "暂不支持自由多轮推理或跨竞品比较。可输入：分析 Notion、查看 Linear 最近变化、查看 Notion 当前价格。"}
    match = re.fullmatch(r"(?:帮我|请)?(?:重新分析|分析)\s*(.+?)(?:\s*这个产品)?", text)
    if match:
        return {"action": "analyze", "name": match[1]}
    match = re.fullmatch(r"打开运行\s+(\d+)", text)
    if match:
        return {"action": "run", "run_id": int(match[1])}
    match = re.fullmatch(r"查看\s*(.+?)\s*(最新报告|最近变化|最近发生了哪些变化|来源|当前价格)", text)
    if match:
        return {"action": {"最新报告": "report", "最近变化": "signals", "最近发生了哪些变化": "signals", "来源": "sources", "当前价格": "pricing"}[match[2]], "name": match[1]}
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+-]*(?: [A-Za-z0-9][A-Za-z0-9.+-]*){0,2}|[\u4e00-\u9fff]{2,12}", text) and not re.search(r"查看|为什么|如何|帮我|请|分析|什么", text):
        return {"action": "analyze", "name": text}
    return {"action": "unsupported", "message": "Natural-language Analyst is not connected yet."}

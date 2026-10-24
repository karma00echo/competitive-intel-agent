"""Limited comparisons with deterministic evidence and comparability gates."""

from decimal import Decimal
from itertools import combinations
import re

from .competitive_matrix import utc


def dates(fact, matrix):
    return {utc(matrix["evidence"][eid]["collected_at"]).date() for eid in fact["evidence_ids"]}


def price_comparability(left, right, matrix):
    if dates(left, matrix) != dates(right, matrix) or len(dates(left, matrix)) != 1:
        return "OBSERVATION_TIME_INCOMPARABLE"
    a, b = left["value"], right["value"]
    for field in ("currency", "billing_period", "billing_unit", "billing_commitment", "region", "tax_status"):
        av, bv = a.get(field), b.get(field)
        if av is None or bv is None or str(av).strip().upper() in {"", "UNKNOWN", "UNSPECIFIED"} or str(bv).strip().upper() in {"", "UNKNOWN", "UNSPECIFIED"}:
            return "PRICE_BASIS_UNKNOWN"
        if str(av).casefold() != str(bv).casefold():
            return "PRICE_BASIS_MISMATCH"
    if a.get("public_status") not in {"PUBLIC", "FREE"} or b.get("public_status") not in {"PUBLIC", "FREE"}:
        return "PRICE_NOT_PUBLIC"
    if a.get("amount") is None or b.get("amount") is None:
        return "PRICE_NOT_PUBLIC"
    for fact in (left, right):
        quotes = [matrix["evidence"][eid]["quote"].casefold() for eid in fact["evidence_ids"]]
        for field in ("region", "tax_status"):
            pattern = r"(?<!\w)" + re.escape(str(fact["value"][field]).casefold()) + r"(?!\w)"
            if not any(re.search(pattern, q) for q in quotes):
                return "PRICE_BASIS_NOT_GROUNDED"
    return None


def build_findings(matrix):
    result = {"findings": [], "limitations": [], "policy": "competitive-findings-v1"}
    selected_ids = {fid for p in matrix["products"] for cell in p["cells"].values() for fid in cell["fact_ids"]}
    facts = [f for fid, f in matrix["facts"].items() if fid in selected_ids and f["verification_status"] == "CONFIRMED"]

    def emit(kind, supported, text):
        evidence = sorted({eid for f in supported for eid in f["evidence_ids"]})
        result["findings"].append({"id": f"finding-{len(result['findings']) + 1}", "kind": kind,
            "statement_type": "ANALYSIS_INFERENCE", "fact_ids": [f["id"] for f in supported],
            "evidence_ids": evidence, "text": text})

    for left, right in combinations(facts, 2):
        if left["product_id"] == right["product_id"] or left["category"] != right["category"]:
            continue
        a, b = left["value"], right["value"]
        names = f"{left['product']} / {right['product']}"
        if left["category"] == "PRICE":
            reason = price_comparability(left, right, matrix)
            if reason:
                result["limitations"].append({"code": reason, "fact_ids": [left["id"], right["id"]]})
                continue
            relation = "lower than" if Decimal(str(a["amount"])) < Decimal(str(b["amount"])) else "higher than" if Decimal(str(a["amount"])) > Decimal(str(b["amount"])) else "equal to"
            emit("LISTED_PRICE_COMPARISON", [left, right],
                 f"{left['product']} {a['plan_name']}: {a['amount']} {a['currency']} is {relation} "
                 f"{right['product']} {b['plan_name']}: {b['amount']} {b['currency']} on the same quoted billing basis. "
                 "This compares listed unit prices only, not equivalent entitlements, total cost or overall value.")
        elif dates(left, matrix) != dates(right, matrix) or len(dates(left, matrix)) != 1:
            result["limitations"].append({"code": "OBSERVATION_TIME_INCOMPARABLE", "fact_ids": [left["id"], right["id"]]})
        elif left["category"] == "FEATURE" and a["normalized_feature_name"].casefold() == b["normalized_feature_name"].casefold():
            emit("DOCUMENTED_COMMON_FEATURE", [left, right],
                 f"{names} both document {a['feature_name']}; availability/status remain product-specific. "
                 "Matching names do not establish identical implementation or quality.")
        elif left["category"] == "POSITIONING":
            emit("POSITIONING_COMPARISON", [left, right],
                 f"{left['product']} positions itself as {a['primary_positioning']}; "
                 f"{right['product']} positions itself as {b['primary_positioning']}. "
                 "These are documented positioning statements, not proof of superiority or suitability.")
    for fact in facts:
        if fact["category"] != "FEATURE" or len(matrix["products"]) < 2: continue
        peers = [f for f in facts if f["category"] == "FEATURE" and f["product_id"] != fact["product_id"]
                 and f["value"]["normalized_feature_name"].casefold() == fact["value"]["normalized_feature_name"].casefold()]
        if not peers:
            emit("DOCUMENTED_DIFFERENTIATOR_CANDIDATE", [fact],
                 f"{fact['product']} documents {fact['value']['feature_name']}. No matching evidence was found in "
                 "the other products' collected sample; this does not mean they lack the feature.")
    result["limitations"].append({"code": "NO_COMPLETENESS_OR_SUITABILITY_RANKING",
        "text": "More comprehensive / better suited claims require coverage and user-requirement evidence not established by this MVP."})
    return result


def validate_synthesis(payload, findings):
    """The model may prioritize supported findings, never author new factual prose."""
    if not isinstance(payload, dict) or set(payload) != {"selected_finding_ids"}:
        raise ValueError("UNSUPPORTED_SYNTHESIS_SCHEMA")
    ids = payload["selected_finding_ids"]
    if not isinstance(ids, list) or not ids or len(ids) > 12 or any(not isinstance(x, str) for x in ids) or len(ids) != len(set(ids)):
        raise ValueError("INVALID_SYNTHESIS_REFERENCES")
    known = {f["id"]: f for f in findings["findings"]}
    if any(x not in known for x in ids):
        raise ValueError("UNSUPPORTED_SYNTHESIS_REFERENCES")
    return [known[x] for x in ids]

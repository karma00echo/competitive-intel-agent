"""Cross-product evidence matrix. Never interprets absence as feature removal."""

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
import json

from .evidence import EvidenceChecker, normalized_evidence
from .fact_comparison import FactNormalizer
from .facts import CandidateFact, EvidenceCheckStatus, FactCategory
from .urls import normalize_url, same_site


@dataclass(frozen=True)
class ResearchProduct:
    name: str
    product_id: int | None
    run_id: int | None
    identity_verified: bool
    status: str = "COMPLETE"
    issues: tuple[str, ...] = ()
    conflicted_fact_keys: tuple[str, ...] = ()


def decode(value):
    return json.loads(value) if isinstance(value, str) else value


def utc(value):
    value = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(value, datetime):
        raise ValueError("Missing observation time")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def dimensions_for(category, value):
    if category == "FEATURE":
        return ["core_features", "differentiation"] + (["ai_capabilities"] if value.get("feature_category") == "AI" else [])
    if category == "POSITIONING":
        return ["positioning"] + (["target_users"] if value.get("target_users") else [])
    if category in {"PLAN", "PRICE"}:
        return ["pricing"]
    return []


def validate_row(row, product):
    """Recheck ownership, observed evidence and original fact provenance together."""
    if not product.identity_verified or not product.product_id or not product.run_id:
        raise ValueError("IDENTITY_UNCERTAIN")
    for key in ("competitor_id", "observation_product_id", "source_product_id", "version_product_id", "origin_source_product_id"):
        if row.get(key) != product.product_id:
            raise ValueError("PRODUCT_ATTRIBUTION_MISMATCH")
    if (row.get("observed_run_id") != product.run_id or row.get("snapshot_run_id") != product.run_id
            or row.get("snapshot_source_id") != row.get("source_id")):
        raise ValueError("OBSERVATION_RELATION_MISMATCH")
    if (row.get("evidence_status") != "CONFIRMED" or row.get("statement_type") != "FACT"
            or row.get("verification_status") != "VERIFIED" or not row.get("is_active")
            or row.get("fetch_status") != "SUCCESS"):
        raise ValueError("UNVERIFIED_EVIDENCE")
    url = row["observed_source_url"]
    if normalize_url(row["requested_url"]) != normalize_url(url) or not same_site(row["final_url"] or url, url):
        raise ValueError("SOURCE_SNAPSHOT_URL_MISMATCH")
    content = row["clean_content"]
    if sha256(content.encode()).hexdigest() != row["clean_hash"]:
        raise ValueError("SNAPSHOT_HASH_MISMATCH")
    value = decode(row["fact_value"])
    candidate = CandidateFact(FactCategory(row["fact_category"]), value, row.get("value_text") or "",
                              row["observed_evidence"], float(row["observed_confidence"]))
    checked = EvidenceChecker().check(candidate, content, url)
    if checked.status != EvidenceCheckStatus.CONFIRMED:
        raise ValueError("EVIDENCE_RECHECK_FAILED")
    if checked.fact_key != row["fact_key"]:
        raise ValueError("FACT_KEY_MISMATCH")
    observed, fetched = utc(row["observed_at"]), utc(row["fetched_at"])
    if fetched > observed:
        raise ValueError("OBSERVATION_TIME_INVALID")
    if candidate.fact_category == FactCategory.POSITIONING:
        # Target-user cells need their own quoted support, not just the primary
        # positioning string checked by the shared validator.
        if any(normalized_evidence(v) not in normalized_evidence(candidate.evidence_text) for v in value["target_users"]):
            raise ValueError("TARGET_USERS_NOT_GROUNDED")
    canonical = FactNormalizer().canonical_json(row["fact_category"], value)
    if canonical != FactNormalizer().canonical_json(row["fact_category"], decode(row["normalized_value"])):
        raise ValueError("FACT_VERSION_VALUE_MISMATCH")
    return value, canonical


def build_matrix(task, products, rows_by_run):
    """rows_by_run must come from Repository, never directly from an API payload."""
    if not 1 <= len(products) <= 3:
        raise ValueError("One target and at most two competitors are supported")
    names = [p.name for p in products]
    if len({n.casefold() for n in names}) != len(names) or names[0] != task.target:
        raise ValueError("Invalid product scope")
    if getattr(task, "status", "READY") != "READY":
        raise ValueError("Task requires clarification")
    explicit = getattr(task, "competitors", [])
    if explicit and {n.casefold() for n in names[1:]} != {n.casefold() for n in explicit}:
        raise ValueError("Explicit competitor scope must be preserved")
    ids = [p.product_id for p in products if p.product_id is not None]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate product identity")
    matrix = {"schema_version": "competitive-matrix-v1", "target": task.target,
              "dimensions": list(task.dimensions), "products": [], "facts": {}, "evidence": {}, "gaps": []}
    if len(products) < 2:
        matrix["gaps"].append({"code": "INSUFFICIENT_COMPARISON_PRODUCTS"})
    for product in products:
        cells = {dim: {"status": "INFORMATION_INSUFFICIENT", "fact_ids": [], "issues": []} for dim in task.dimensions}
        item = {"name": product.name, "product_id": product.product_id, "research_run_id": product.run_id,
                "identity_verified": product.identity_verified, "research_status": product.status, "cells": cells}
        matrix["products"].append(item)
        for issue in product.issues:
            matrix["gaps"].append({"product": product.name, "code": issue})
        if not product.identity_verified:
            for cell in cells.values(): cell["status"] = "IDENTITY_UNCERTAIN"
            matrix["gaps"].append({"product": product.name, "code": "IDENTITY_UNCERTAIN"})
            continue
        groups = {}
        for row in rows_by_run.get(product.run_id, []):
            try:
                value, canonical = validate_row(row, product)
            except (ValueError, KeyError, TypeError) as exc:
                code = str(exc) if str(exc).isupper() else "INVALID_EVIDENCE_ROW"
                matrix["gaps"].append({"product": product.name, "code": code, "fact_id": row.get("id")})
                continue
            group = groups.setdefault((row["fact_category"], row["fact_key"]), {})
            fid = "f-" + sha256(f"{product.product_id}|{row['fact_key']}|{canonical}".encode()).hexdigest()[:24]
            record = group.setdefault(fid, {"id": fid, "product_id": product.product_id, "product": product.name,
                "category": row["fact_category"], "fact_key": row["fact_key"], "value": value,
                "verification_status": "CONFIRMED", "evidence_ids": []})
            eid = f"o-{row['observation_id']}"
            if eid not in record["evidence_ids"]:
                record["evidence_ids"].append(eid)
                matrix["evidence"][eid] = {"id": eid, "product_id": product.product_id, "fact_id": row["id"],
                    "source_id": row["source_id"], "snapshot_id": row["observed_snapshot_id"],
                    "observation_id": row["observation_id"], "run_id": row["observed_run_id"],
                    "url": row["observed_source_url"], "quote": row["observed_evidence"],
                    "collected_at": utc(row["fetched_at"]).isoformat(), "observed_at": utc(row["observed_at"]).isoformat(),
                    "confidence": float(row["observed_confidence"]), "verification_status": "CONFIRMED",
                    "snapshot_hash": row["clean_hash"]}
        for group in groups.values():
            conflict = len(group) > 1 or any(f["fact_key"] in product.conflicted_fact_keys for f in group.values())
            for fid, fact in group.items():
                if conflict: fact["verification_status"] = "SOURCE_CONFLICT"
                matrix["facts"][fid] = fact
                for dim in dimensions_for(fact["category"], fact["value"]):
                    if dim in cells:
                        cells[dim]["fact_ids"].append(fid)
                        if conflict: cells[dim]["issues"].append("SOURCE_CONFLICT")
        for dim, cell in cells.items():
            cell["status"] = "SOURCE_CONFLICT" if cell["issues"] else "EVIDENCED" if cell["fact_ids"] else "INFORMATION_INSUFFICIENT"
            if cell["status"] != "EVIDENCED":
                matrix["gaps"].append({"product": product.name, "dimension": dim, "code": cell["status"]})
        if product.status != "COMPLETE":
            matrix["gaps"].append({"product": product.name, "code": "PRODUCT_RESEARCH_PARTIAL"})
    for dim in task.dimensions:
        samples = [(p, p["cells"][dim]) for p in matrix["products"] if p["cells"][dim]["fact_ids"]]
        days = {utc(matrix["evidence"][eid]["collected_at"]).date() for _, cell in samples
                for fid in cell["fact_ids"] for eid in matrix["facts"][fid]["evidence_ids"]}
        if len(samples) > 1 and len(days) > 1:
            for product, cell in samples:
                cell["issues"].append("OBSERVATION_TIME_INCOMPARABLE")
                if cell["status"] != "SOURCE_CONFLICT": cell["status"] = "TIME_INCOMPARABLE"
                matrix["gaps"].append({"product": product["name"], "dimension": dim, "code": "OBSERVATION_TIME_INCOMPARABLE"})
    matrix["status"] = "PARTIAL" if matrix["gaps"] else "COMPLETE"
    return matrix

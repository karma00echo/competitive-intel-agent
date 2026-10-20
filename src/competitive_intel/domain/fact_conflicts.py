"""Bounded cross-source diagnostics; never decides which conflicting fact wins."""
import re

from .fact_comparison import FactNormalizer


def _excerpt(value: str, limit: int) -> str:
    # Source text is untrusted: suppress credential-shaped fragments before clipping.
    value = re.sub(r"(?i)\b(?:bearer\s+|sk-)[^\s\"<>]+", "[REDACTED]", value)
    value = re.sub(
        r"(?i)\b(?:api[_-]?key|authorization|password|token)\s*[:=]\s*\S+",
        "[REDACTED]", value,
    )
    value = " ".join(value.split())
    return value[:limit] + ("…" if len(value) > limit else "")


def conflict_side(candidate, source_id: int, snapshot_id: int) -> dict:
    canonical = FactNormalizer().canonical_json(
        candidate.fact_category.value, candidate.fact_value
    )
    return {
        "source_id": source_id,
        "snapshot_id": snapshot_id,
        "normalized_value": _excerpt(canonical, 1000),
        "evidence": _excerpt(candidate.evidence_text, 360),
    }


def conflict_diagnostic(identity: tuple[str, str], previous: dict, incoming: dict) -> dict:
    return {
        "fact_type": identity[0],
        "canonical_identity": _excerpt(identity[1], 180),
        "reason": "SAME_IDENTITY_DIFFERENT_CANONICAL_VALUE",
        "interpretation": "UNRESOLVED_NOT_PROOF_OF_REAL_WORLD_CONTRADICTION",
        "action": "REJECT_INCOMING_KEEP_RUN_UNACTIVATED",
        "previous": previous,
        "incoming": incoming,
    }

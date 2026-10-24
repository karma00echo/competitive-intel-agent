"""Pure evidence-matrix tests, no model/network/database calls."""

from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from types import SimpleNamespace

import pytest

from competitive_intel.domain.competitive_matrix import ResearchProduct, build_matrix
from competitive_intel.domain.competitive_findings import build_findings, validate_synthesis
from competitive_intel.domain.fact_normalization import normalize_fact
from competitive_intel.domain.facts import CandidateFact, FactCategory
from competitive_intel.domain.fact_comparison import FactNormalizer


def row(product=1, *, category="FEATURE", number=1, value=None, quote=None, day=0):
    value = value or {"feature_name": "Docs", "normalized_feature_name": "docs", "feature_description": "Docs collaboration",
        "feature_category": "DOCUMENTS", "availability": None, "related_plan": None, "status": "AVAILABLE"}
    quote = quote or "Docs collaboration is available."
    when = datetime(2026, 1, 1) + timedelta(days=day)
    fact = normalize_fact(CandidateFact(FactCategory(category), value, quote, quote, 0.9))
    return dict(id=product * 100 + number, observation_id=product * 100 + number,
        competitor_id=product, observation_product_id=product, source_product_id=product,
        version_product_id=product, origin_source_product_id=product, observed_run_id=product,
        snapshot_run_id=product, snapshot_source_id=number, source_id=number,
        observed_snapshot_id=number, evidence_status="CONFIRMED", statement_type="FACT",
        verification_status="VERIFIED", is_active=True, fetch_status="SUCCESS",
        observed_source_url=f"https://product{product}.example/{number}", requested_url=f"https://product{product}.example/{number}",
        final_url=f"https://product{product}.example/{number}", clean_content=quote,
        clean_hash=sha256(quote.encode()).hexdigest(), fact_value=fact.fact_value,
        fact_category=category, fact_key=fact.fact_key, observed_evidence=quote, observed_confidence=0.9,
        observed_at=when + timedelta(seconds=1), fetched_at=when,
        normalized_value=FactNormalizer().normalize(category, fact.fact_value))


def price(product=1, amount="10", **changes):
    value = dict(plan_name="Pro", amount=amount, currency="USD", billing_period="MONTH", billing_unit="USER",
                 billing_commitment="MONTHLY_BILLING", region="US", tax_status="exclusive", public_status="PUBLIC")
    value.update(changes)
    quote = f"Pro costs ${amount} USD per user per month, billed monthly, US region, exclusive tax."
    return row(product, category="PRICE", value=value, quote=quote)


def matrix(rows=None, dimensions=("core_features",), products=None):
    products = products or [ResearchProduct("Alpha", 1, 1, True), ResearchProduct("Beta", 2, 2, True), ResearchProduct("Gamma", 3, 3, True)]
    return build_matrix(SimpleNamespace(target="Alpha", dimensions=list(dimensions)), products,
                        rows if rows is not None else {n: [row(n)] for n in range(1, 4)})


def test_three_products_and_common_feature_retain_all_evidence_links():
    value = matrix()
    assert value["status"] == "COMPLETE"
    assert len(value["products"]) == 3 and len(value["facts"]) == 3
    findings = build_findings(value)
    assert len(findings["findings"]) == 3
    for finding in findings["findings"]:
        assert finding["statement_type"] == "ANALYSIS_INFERENCE"
        assert len(finding["fact_ids"]) == 2 and len(finding["evidence_ids"]) == 2


def test_missing_dimension_is_unknown_not_absence():
    value = matrix(dimensions=("core_features", "pricing"))
    assert value["status"] == "PARTIAL"
    assert all(p["cells"]["pricing"]["status"] == "INFORMATION_INSUFFICIENT" for p in value["products"])


def test_target_without_competitors_cannot_be_complete_comparison():
    value = matrix({1: [row()]}, products=[ResearchProduct("Alpha", 1, 1, True)])
    assert value["status"] == "PARTIAL" and value["facts"]
    assert not build_findings(value)["findings"]


def test_multi_source_dedup_keeps_observations():
    value = matrix({1: [row(1), row(1, number=2)], 2: [row(2)], 3: [row(3)]})
    own = [f for f in value["facts"].values() if f["product_id"] == 1]
    assert len(own) == 1 and len(own[0]["evidence_ids"]) == 2


def test_conflict_retains_both_claims_but_excludes_them_from_findings():
    other = row(1, number=2)
    other["fact_value"]["availability"] = "BETA"
    other["normalized_value"] = FactNormalizer().normalize("FEATURE", other["fact_value"])
    value = matrix({1: [row(1), other], 2: [row(2)], 3: [row(3)]})
    assert value["products"][0]["cells"]["core_features"]["status"] == "SOURCE_CONFLICT"
    forbidden = {f["id"] for f in value["facts"].values() if f["product_id"] == 1}
    assert all(not forbidden.intersection(f["fact_ids"]) for f in build_findings(value)["findings"])


@pytest.mark.parametrize("field", ["competitor_id", "observation_product_id", "source_product_id", "version_product_id", "origin_source_product_id"])
def test_wrong_product_association_rejected(field):
    broken = row(); broken[field] = 2
    value = matrix({1: [broken]})
    assert not value["facts"] and any(g["code"] == "PRODUCT_ATTRIBUTION_MISMATCH" for g in value["gaps"])


@pytest.mark.parametrize("field,invalid", [("snapshot_run_id", 999), ("snapshot_source_id", 999),
    ("clean_hash", "invalid"), ("evidence_status", "PENDING"), ("statement_type", "INFERENCE"),
    ("verification_status", "REJECTED"), ("observed_evidence", "Unsupported Docs claim"),
    ("fact_key", "feature.wrong"), ("final_url", "https://other.example/")])
def test_broken_provenance_or_unsupported_fact_is_not_matrix_evidence(field, invalid):
    broken = row(); broken[field] = invalid
    assert not matrix({1: [broken]})["facts"]


def test_unknown_identity_and_failed_product_keep_other_evidence():
    products = [ResearchProduct("Alpha", 1, 1, True), ResearchProduct("Beta", None, None, False),
                ResearchProduct("Gamma", 3, 3, True, "PARTIAL", ("BUDGET_EXHAUSTED",))]
    value = matrix(products=products)
    assert value["status"] == "PARTIAL" and len(value["facts"]) == 2
    assert value["products"][1]["cells"]["core_features"]["status"] == "IDENTITY_UNCERTAIN"


def test_same_basis_prices_compare_only_listed_units_not_product_value():
    value = matrix({1: [price()], 2: [price(2, "20")], 3: []}, dimensions=("pricing",))
    findings = build_findings(value)["findings"]
    assert len(findings) == 1
    assert "lower than" in findings[0]["text"] and "not equivalent entitlements" in findings[0]["text"]


def test_currency_code_does_not_prove_region():
    value = matrix({1: [price()], 2: [price(2, "20")]}, dimensions=("pricing",))
    for evidence in value["evidence"].values():
        evidence["quote"] = evidence["quote"].replace("US region, ", "")
    findings = build_findings(value)
    assert not findings["findings"]
    assert any(item["code"] == "PRICE_BASIS_NOT_GROUNDED" for item in findings["limitations"])


@pytest.mark.parametrize("field,other", [("region", "EU"), ("tax_status", "UNKNOWN"), ("currency", "EUR"),
                                     ("billing_commitment", "ANNUAL_BILLING"), ("billing_period", "YEAR"), ("billing_unit", "WORKSPACE")])
def test_price_basis_mismatch_cannot_be_called_cheaper(field, other):
    # Modify the matrix only after row validation to test the comparison gate itself.
    value = matrix({1: [price()], 2: [price(2, "20")]}, dimensions=("pricing",))
    second = next(f for f in value["facts"].values() if f["product_id"] == 2)
    second["value"][field] = other
    findings = build_findings(value)
    assert not findings["findings"]
    assert any(x["code"] in {"PRICE_BASIS_MISMATCH", "PRICE_BASIS_UNKNOWN"} for x in findings["limitations"])


def test_different_collection_days_are_explicitly_incomparable():
    a, b = price(), price(2, "20")
    b["fetched_at"] += timedelta(days=1); b["observed_at"] += timedelta(days=1)
    value = matrix({1: [a], 2: [b]}, dimensions=("pricing",))
    assert value["products"][0]["cells"]["pricing"]["status"] == "TIME_INCOMPARABLE"
    assert not build_findings(value)["findings"]


@pytest.mark.parametrize("payload", [{"selected_finding_ids": ["invented"]}, {"text": "Alpha is best"},
    {"selected_finding_ids": []}, {"selected_finding_ids": ["finding-1", "finding-1"]}])
def test_synthesis_without_valid_support_cannot_be_published(payload):
    with pytest.raises(ValueError): validate_synthesis(payload, build_findings(matrix()))


def test_supported_synthesis_selects_existing_text_and_evidence_only():
    findings = build_findings(matrix())
    result = validate_synthesis({"selected_finding_ids": ["finding-1"]}, findings)
    assert result == [findings["findings"][0]]


def test_repeat_matrix_build_is_deterministic_and_read_only():
    rows = {1: [row()], 2: [row(2)], 3: [row(3)]}; before = deepcopy(rows)
    assert matrix(rows) == matrix(rows) and rows == before


def test_explicit_competitors_cannot_be_silently_replaced():
    task = SimpleNamespace(target="Alpha", competitors=["Beta", "Gamma"], dimensions=["core_features"])
    with pytest.raises(ValueError, match="scope"):
        build_matrix(task, [ResearchProduct("Alpha", 1, 1, True), ResearchProduct("Other", 2, 2, True)], {})


def test_conflict_rejected_during_extraction_still_blocks_surviving_fact():
    products = [ResearchProduct("Alpha", 1, 1, True, conflicted_fact_keys=("feature.docs",)),
                ResearchProduct("Beta", 2, 2, True)]
    value = matrix(products=products)
    assert value["products"][0]["cells"]["core_features"]["status"] == "SOURCE_CONFLICT"


class SynthesisTransport:
    def __init__(self, mode="ok"):
        self.mode, self.calls = mode, 0

    def post(self, url, **kwargs):
        import json
        from tests.discovery_support import Response
        self.calls += 1
        assert kwargs["allow_redirects"] is False
        if self.mode == "http_error":
            return Response({}, status=503)
        answer = {"selected_finding_ids": ["invented" if self.mode == "unsupported" else "finding-1"]}
        return Response({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                         "usage": {"total_tokens": 50}})

    def close(self): pass


def synthesis_context(mode="ok", limits=None):
    from tests.discovery_support import settings
    from competitive_intel.domain.task_budget import TaskBudget
    from competitive_intel.services.research_context import ResearchContext
    transport = SynthesisTransport(mode)
    context = ResearchContext(settings(), allow_paid=True, budget=TaskBudget(limits), session_factory=lambda _: transport)
    return context, transport


def test_synthesis_inherits_discovery_and_extraction_budget_without_reset():
    from competitive_intel.services.competitive_analysis_service import CompetitiveAnalysisService
    context, transport = synthesis_context()
    context.budget.reserve(searches=4, fetches=6, models=3, extraction=2, evaluation=1, tokens=100, cost_microusd=200)
    result = CompetitiveAnalysisService().analyze(matrix(), context)
    assert result["status"] == "COMPLETE" and transport.calls == 1
    used = result["budget"]["used"]
    assert used["searches"] == 4 and used["fetches"] == 6 and used["models"] == 4 and used["synthesis"] == 1
    assert used["tokens"] > 100 and used["cost_microusd"] > 200
    assert result["budget"]["task_id"] == context.budget.task_id
    again = CompetitiveAnalysisService().analyze(matrix(), context)
    assert again["status"] == "PARTIAL" and not again["conclusions"] and transport.calls == 1
    assert again["matrix"]["facts"] and again["synthesis_status"] == "BUDGET_EXHAUSTED"


@pytest.mark.parametrize("mode", ["http_error", "unsupported"])
def test_synthesis_failure_keeps_matrix_without_fabricating_conclusions(mode):
    from competitive_intel.services.competitive_analysis_service import CompetitiveAnalysisService
    context, transport = synthesis_context(mode)
    result = CompetitiveAnalysisService().analyze(matrix(), context)
    assert result["status"] == "PARTIAL" and result["synthesis_status"] == "FAILED"
    assert result["matrix"]["facts"] and not result["conclusions"] and transport.calls == 1
    assert result["budget"]["used"]["synthesis"] == 1


def test_token_exhaustion_stops_transport_and_retains_evidence():
    from competitive_intel.domain.task_budget import BudgetLimits
    from competitive_intel.services.competitive_analysis_service import CompetitiveAnalysisService
    context, transport = synthesis_context(limits=BudgetLimits(tokens=10))
    result = CompetitiveAnalysisService().analyze(matrix(), context)
    assert transport.calls == 0 and result["budget"]["exhausted"] == "tokens"
    assert result["status"] == "PARTIAL" and result["matrix"]["facts"]


def test_no_comparable_findings_does_not_call_model():
    from competitive_intel.services.competitive_analysis_service import CompetitiveAnalysisService
    context, transport = synthesis_context()
    result = CompetitiveAnalysisService().analyze(matrix({}), context)
    assert not result["conclusions"] and transport.calls == 0
    assert result["issues"] == ["INSUFFICIENT_COMPARABLE_EVIDENCE"]

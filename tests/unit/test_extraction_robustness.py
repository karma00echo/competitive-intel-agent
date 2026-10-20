"""Run-35 failure shapes using short public/synthetic excerpts, never live APIs."""
from copy import deepcopy

import pytest

from competitive_intel.domain.facts import FactCategory
from competitive_intel.domain.fact_conflicts import conflict_side, conflict_diagnostic
from competitive_intel.infrastructure.facts.llm_provider import PAGE_INSTRUCTIONS
from test_llm_fact_provider import fact
from test_page_aware_extraction import extract, release, price


@pytest.mark.parametrize("name,description,guess", [
    ("Data syncs", "Pull live Salesforce and Jira data right into Notion.", "INTEGRATION"),
    ("Notion Agent", "Chat with your personal agent that takes action across your work.", "AI"),
    ("Custom Agents", "Build always-on agents for your team's workflows.", "AI"),
    ("Agent Skills", "Use repeatable playbooks that teach agents how you work.", "AI"),
    ("Dynamic triggers", "Kick off agent work the moment something changes.", "AUTOMATION"),
    ("Agent Orchestration", "Direct Claude, Cursor, and other agents from Notion.", "AI"),
])
def test_run35_inferred_category_rejected_but_null_supported(name, description, guess):
    item = fact()
    item["fact_value"].update(feature_name=name, normalized_feature_name=name,
        feature_description=description, feature_category=guess, status=None)
    item["evidence_text"] = text = f"{name} → {description}"
    rejected = extract([item], content=text)
    assert rejected.error == "UNGROUNDED_FIELD"
    assert rejected.evidence_diagnostics[0]["field_name"] == "feature_category"
    item["fact_value"]["feature_category"] = None
    accepted = extract([item], content=text)
    assert not accepted.error
    assert accepted.candidate_facts[0].fact_value["feature_category"] == "OTHER"
    assert accepted.contract_adaptations[0]["model_value"] is None


@pytest.mark.parametrize("name", ["Business", "Enterprise"])
@pytest.mark.parametrize("scope", ["missing", "empty_list", "full_quote"])
def test_plan_features_require_same_quote(name, scope):
    heading = f"{name} For growing businesses."
    feature = "Secure single sign-on."
    text = heading + "\n" + feature
    item = {"fact_category": "PLAN", "fact_value": {
        "plan_name": name, "normalized_plan_name": name,
        "plan_description": "For growing businesses.", "target_user": None,
        "included_features": [] if scope == "empty_list" else [feature],
        "public_status": None,
    }, "evidence_text": text if scope == "full_quote" else heading, "confidence": 0.9}
    result = extract([item], kind="PRICING", content=text, allowed=(FactCategory.PLAN,))
    assert bool(result.error) == (scope == "missing")
    if scope == "missing":
        assert result.evidence_diagnostics[0]["field_name"] == "included_features[0]"


@pytest.mark.parametrize("include_notice", [True, False])
def test_release_quote_cannot_skip_video_notice(include_notice):
    item = release()
    notice = "Uh-oh! Your ad blocker is preventing the video from playing."
    text = f"New editor\n{notice}\nEdit together."
    item["evidence_text"] = text if include_notice else "New editor\nEdit together."
    result = extract([item], kind="CHANGELOG", content=text,
                     allowed=(FactCategory.PRODUCT_UPDATE,))
    assert bool(result.error) != include_notice


def test_release_named_feature_elsewhere_is_not_in_selected_evidence():
    item = release()
    item["fact_value"]["affected_features"] = ["Notion MCP"]
    result = extract([item], kind="CHANGELOG",
        content=item["evidence_text"] + "\nAnother release: Notion MCP.",
        allowed=(FactCategory.PRODUCT_UPDATE,))
    assert result.evidence_diagnostics[0]["field_name"] == "affected_features[0]"
    assert result.error == "UNGROUNDED_FIELD"


def test_contract_explicitly_limits_granularity_not_validator():
    assert "included_features=[]" in PAGE_INSTRUCTIONS["PRICING"]
    assert "no per-item evidence" in PAGE_INSTRUCTIONS["PRICING"]
    assert "do not imply AI" in PAGE_INSTRUCTIONS["FEATURES"]
    assert "affected_features=[]" in PAGE_INSTRUCTIONS["CHANGELOG"]


def test_conflict_diagnostic_bounded_redacted_and_unresolved():
    candidate = extract([fact()]).candidate_facts[0]
    previous = conflict_side(candidate, 1, 10)
    incoming = conflict_side(candidate, 2, 11)
    result = conflict_diagnostic(("FEATURE", "feature.docs"), previous, incoming)
    assert result["previous"]["snapshot_id"] == 10
    assert result["incoming"]["source_id"] == 2
    assert result["interpretation"].startswith("UNRESOLVED")
    from dataclasses import replace
    unsafe = replace(candidate, evidence_text="Authorization: Bearer secret-value " + "x" * 900)
    side = conflict_side(unsafe, 2, 11)
    assert "secret-value" not in side["evidence"]
    assert len(side["evidence"]) <= 361


def test_distinct_explicit_payment_commitments_have_distinct_identities():
    a = price(period="MONTH")
    a["fact_value"]["billing_commitment"] = "ANNUAL_BILLING"
    a["evidence_text"] = "Pro $10/month paid annually"
    b = deepcopy(a)
    b["fact_value"]["billing_commitment"] = "MONTHLY_BILLING"
    b["evidence_text"] = "Pro $10/month paid monthly"
    result = extract([a, b], kind="PRICING",
        content=a["evidence_text"] + "\n" + b["evidence_text"],
        allowed=(FactCategory.PRICE,))
    assert not result.error
    assert len(result.candidate_facts) == 2

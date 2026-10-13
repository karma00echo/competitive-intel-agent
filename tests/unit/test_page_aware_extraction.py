"""Page contracts and fact-isolated validation; no network."""
from copy import deepcopy
from dataclasses import replace

import pytest

from competitive_intel.domain.facts import FactCategory
from competitive_intel.infrastructure.facts.llm_provider import LLMFactExtractionProvider, output_schema
from test_llm_fact_provider import Session, Response, config, request, fact, TEXT


def extract(items, *, kind="FEATURES", content=TEXT, allowed=None):
    req = replace(request(), source_type=kind, clean_content=content,
                  allowed_fact_categories=allowed or (FactCategory.FEATURE,))
    return LLMFactExtractionProvider(config(), session=Session([Response(
        {"snapshot_id":12,"facts":items})])).extract(req)


@pytest.mark.parametrize("kind,expected", [
    ("HOMEPAGE", {"FEATURE", "POSITIONING"}), ("FEATURES", {"FEATURE"}),
    ("PRICING", {"PLAN", "PRICE"}), ("CHANGELOG", {"PRODUCT_UPDATE"}),
])
def test_page_specific_schema(kind, expected):
    schema = output_schema(replace(request(), source_type=kind, allowed_fact_categories=tuple(FactCategory)))
    variants = schema["properties"]["facts"]["items"]["anyOf"]
    assert {v["properties"]["fact_category"]["enum"][0] for v in variants} == expected


@pytest.mark.parametrize("bad", [None, {"garbage":"not a fact"},
    {**fact(), "evidence_text":"invented"},
    {**fact(), "fact_value":{**fact()["fact_value"], "feature_description":"invented"}}])
def test_good_fact_survives_invalid_neighbor(bad):
    result = extract([fact(), bad])
    assert len(result.candidate_facts) == 1
    assert result.candidate_facts[0].evidence_text == TEXT
    assert result.error
    assert result.page_status == "PARTIAL_ERROR"
    assert result.returned_fact_count == 2
    assert len(result.fact_rejections) == 1
    assert result.fact_rejections[0]["fact_index"] == 1


def test_duplicate_skip_is_deterministic_and_audited():
    result = extract([fact(), deepcopy(fact())])
    assert result.error is None
    assert len(result.candidate_facts) == 1
    assert result.duplicates == ({"fact_index":1,"kept_fact_index":0,
        "reason":"IDENTICAL_CANONICAL_FACT","action":"SKIPPED"},)


def test_conflicting_identity_is_not_silently_merged():
    second = fact()
    second["fact_value"]["feature_description"] = "teams edit documents"
    result = extract([fact(),second])
    assert result.error == "CONFLICTING_FACT_IDENTITY"
    assert not result.candidate_facts
    assert len(result.fact_rejections) == 2
    paired = result.fact_rejections[1]
    assert paired["canonical_identity"] == "feature.docs"
    assert paired["fact_type"] == "FEATURE"
    assert paired["snapshot_id"] == 12
    assert paired["old_normalized_value"] != paired["new_normalized_value"]
    assert paired["old_evidence"] == paired["new_evidence"] == TEXT
    assert paired["resolution"] == "REJECT_ALL_CONFLICTING_VALUES"


@pytest.mark.parametrize("reverse", [False, True])
def test_positioning_conflict_rejects_both_orders(reverse):
    def positioning(quote):
        return {"fact_category":"POSITIONING", "fact_value":{
            "primary_positioning":quote,"public_description":quote,
            "target_users":[],"primary_use_cases":[],"deployment_type":None},
            "evidence_text":quote,"confidence":0.9}
    items = [positioning("A workspace for teams."), positioning("Tools for research.")]
    if reverse:
        items.reverse()
    result = extract(items, kind="HOMEPAGE", content="A workspace for teams.\nTools for research.",
                     allowed=(FactCategory.POSITIONING,))
    assert result.error == "CONFLICTING_FACT_IDENTITY"
    assert not result.candidate_facts
    assert {r["canonical_identity"] for r in result.fact_rejections} == {"positioning.primary"}


@pytest.mark.parametrize("quote,accepted", [
    ("New editor\nVideo unavailable.\nEdit together.", True),
    ("New editor  Video unavailable.\r\n  Edit together.", True),
    ("New editor\nEdit together.", False),
    ("New editor lets everyone collaborate.", False),
])
def test_contiguous_evidence_cannot_skip_intervening_text(quote, accepted):
    item = release()
    item["evidence_text"] = quote
    result = extract([item], kind="CHANGELOG",
                     content="New editor\nVideo unavailable.\nEdit together.",
                     allowed=(FactCategory.PRODUCT_UPDATE,))
    assert (result.error is None) == accepted
    if not accepted:
        assert result.error == "EVIDENCE_NOT_FOUND"
        assert not result.candidate_facts


def price(currency=None, period=None):
    return {"fact_category":"PRICE", "fact_value":{
        "plan_name":"Pro", "amount":"10", "currency":currency,
        "billing_period":period, "billing_unit":None, "billing_commitment":None,
        "region":None, "tax_status":None, "public_status":None},
        "evidence_text":"Pro $10", "confidence":0.9}


def test_price_null_currency_and_dimensions_preserve_unknown():
    result = extract([price()], kind="PRICING", content="Pro $10", allowed=(FactCategory.PRICE,))
    assert not result.error
    value = result.candidate_facts[0].fact_value
    assert value["currency"] is None
    assert value["billing_period"] == "UNKNOWN"


@pytest.mark.parametrize("item", [price("USD"), price(period="MONTH"),
    {**price(), "evidence_text":"$10"}])
def test_price_no_dollar_currency_or_layout_inference(item):
    result = extract([item], kind="PRICING", content="Pro $10", allowed=(FactCategory.PRICE,))
    assert result.error
    assert not result.candidate_facts


def release(date=None):
    return {"fact_category":"PRODUCT_UPDATE","fact_value":{
        "update_title":"New editor", "published_date":date, "update_type":None,
        "affected_features":[], "summary":"Edit together.", "availability":None,"status":None},
        "evidence_text":"New editor — Edit together.","confidence":0.9}


def test_release_no_invented_date_status_or_plans():
    result = extract([release()], kind="CHANGELOG", content="New editor — Edit together.",
                     allowed=(FactCategory.PRODUCT_UPDATE,))
    assert not result.error
    assert result.candidate_facts[0].fact_value["published_date"] is None
    assert result.candidate_facts[0].fact_value["status"] == "UNKNOWN"
    bad = extract([release("2026-10-13")], kind="CHANGELOG", content="New editor — Edit together.",
                  allowed=(FactCategory.PRODUCT_UPDATE,))
    assert bad.error and not bad.candidate_facts


def test_no_facts_is_not_an_error_but_blank_input_still_is():
    result = extract([])
    assert result.page_status == "NO_FACTS" and not result.error
    assert extract([],content="").error == "EMPTY_CONTENT"


def test_max_tokens_still_participates_in_existing_cache_policy():
    a = LLMFactExtractionProvider(config(max_output_tokens=2000)).policy_key
    b = LLMFactExtractionProvider(config(max_output_tokens=6000)).policy_key
    assert a != b  # Deliberately deferred cache-identity redesign.


@pytest.mark.parametrize("audience,accepted", [([], True), (["companies"], True), (["teams"], False)])
def test_positioning_audience_must_be_literal(audience, accepted):
    quote = "The most ambitious companies run on Acme."
    item = {"fact_category":"POSITIONING", "fact_value":{
        "primary_positioning":quote, "public_description":quote,
        "target_users":audience, "primary_use_cases":[], "deployment_type":None},
        "evidence_text":quote, "confidence":0.9}
    result = extract([item], kind="HOMEPAGE", content=quote,
                     allowed=(FactCategory.POSITIONING,))
    assert (result.error is None) == accepted
    if not accepted:
        assert not result.candidate_facts
        assert result.evidence_diagnostics[0]["field_name"] == "target_users[0]"


@pytest.mark.parametrize("period,unit,accepted", [(None, None, True),
    ("USAGE_BASED", None, False), (None, "USAGE", False), ("USAGE_BASED", "USAGE", False)])
def test_credit_price_does_not_infer_billing_dimensions(period, unit, accepted):
    item = price(period=period)
    item["fact_value"]["billing_unit"] = unit
    quote = "Pro $10 per 1,000 monthly Acme credits."
    item["evidence_text"] = quote
    result = extract([item], kind="PRICING", content=quote, allowed=(FactCategory.PRICE,))
    assert (result.error is None) == accepted
    if accepted:
        value = result.candidate_facts[0].fact_value
        assert value["amount"] == "10" and value["currency"] is None
        assert value["billing_period"] == value["billing_unit"] == "UNKNOWN"
        assert result.candidate_facts[0].evidence_text == quote
    else:
        assert not result.candidate_facts


def test_explicit_monthly_billing_still_supported():
    item = price(period="MONTH")
    item["fact_value"]["billing_commitment"] = "MONTHLY_BILLING"
    item["evidence_text"] = "Pro $10 billed monthly"
    result = extract([item], kind="PRICING", content=item["evidence_text"],
                     allowed=(FactCategory.PRICE,))
    assert not result.error


def test_contract_explains_audience_and_credit_dimensions():
    from competitive_intel.infrastructure.facts.llm_provider import PAGE_INSTRUCTIONS
    assert "Never substitute teams for companies" in PAGE_INSTRUCTIONS["HOMEPAGE"]
    assert "monthly' modifies credits" in PAGE_INSTRUCTIONS["PRICING"]
    for kind, category, fields in [
        ("HOMEPAGE", FactCategory.POSITIONING, ["target_users"]),
        ("PRICING", FactCategory.PRICE, ["billing_period", "billing_unit", "billing_commitment"]),
    ]:
        schema = output_schema(replace(request(), source_type=kind, allowed_fact_categories=(category,)))
        props = schema["properties"]["facts"]["items"]["anyOf"][0]["properties"]["fact_value"]["properties"]
        assert all("description" in props[field] for field in fields)


@pytest.mark.parametrize("name,model_name,expected", [
    ("Free", "free", "free"), ("Plus", "Plus", "plus"),
    ("Business", "business", "business"), ("Enterprise", "enterprise", "enterprise"),
    ("Pro Plus", "pro-plus", "pro_plus"), ("Free", "Enterprise", None),
])
def test_server_owned_plan_normalization(name, model_name, expected):
    quote = f"{name} For growing organizations."
    item = {"fact_category":"PLAN", "fact_value":{
        "plan_name":name, "normalized_plan_name":model_name,
        "plan_description":"For growing organizations.", "target_user":None,
        "included_features":[], "public_status":None}, "evidence_text":quote,"confidence":0.9}
    result = extract([item],kind="PRICING",content=quote,allowed=(FactCategory.PLAN,))
    if expected is None:
        assert result.error == "UNSUPPORTED_NORMALIZED_NAME"
        assert not result.candidate_facts
    else:
        assert not result.error
        assert result.candidate_facts[0].fact_value["normalized_plan_name"] == expected
        audit = next(x for x in result.contract_adaptations if x["reason"] == "SERVER_PLAN_SLUG")
        assert audit["model_value"] == model_name and audit["stored_value"] == expected


@pytest.mark.parametrize("include_heading", [True, False])
def test_price_requires_subject_in_contiguous_quote(include_heading):
    quote = "Custom Agents\nAgents work for you. Free to try, then $10 per 1,000 monthly credits."
    item = price()
    item["fact_value"]["plan_name"] = "Custom Agents"
    item["evidence_text"] = quote if include_heading else quote.split("\n")[1]
    result = extract([item],kind="PRICING",content=quote,allowed=(FactCategory.PRICE,))
    assert (result.error is None) == include_heading
    if not include_heading:
        assert result.evidence_diagnostics[0]["field_name"] == "plan_name"


@pytest.mark.parametrize("payment,commitment", [("annually", "ANNUAL_BILLING"),
    ("monthly", "MONTHLY_BILLING")])
def test_price_period_and_payment_are_independent(payment, commitment):
    item = price(period="MONTH")
    item["fact_value"]["billing_commitment"] = commitment
    item["evidence_text"] = f"Pro $10/month/domain paid {payment}"
    result = extract([item],kind="PRICING",content=item["evidence_text"],allowed=(FactCategory.PRICE,))
    assert not result.error
    value = result.candidate_facts[0].fact_value
    assert value["billing_period"] == "MONTH"
    assert value["billing_unit"] == "UNKNOWN"
    assert value["billing_commitment"] == commitment
    # /month is not evidence for a yearly payment commitment.
    item["evidence_text"] = "Pro $10/month/domain"
    assert extract([item],kind="PRICING",content=item["evidence_text"],
                   allowed=(FactCategory.PRICE,)).error == "UNGROUNDED_FIELD"

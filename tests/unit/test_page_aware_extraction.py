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
    assert len(result.candidate_facts) == 1
    assert len(result.fact_rejections) == 1


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

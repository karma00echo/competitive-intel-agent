import json

from competitive_intel.web.display import FactDisplayFormatter


def test_price_is_human_readable() -> None:
    value = {
        "plan_name": "Plus",
        "amount": "12",
        "currency": "USD",
        "billing_period": "MONTH",
        "billing_unit": "USER",
        "billing_commitment": "ANNUAL_BILLING",
    }
    assert FactDisplayFormatter().format("PRICE", value) == (
        "Plus：12 USD / 用户 / 月，按年计费"
    )


def test_supported_fact_categories_are_not_raw_json() -> None:
    formatter = FactDisplayFormatter()
    cases = {
        "PLAN": ({"plan_name": "Business", "description": "团队方案"}, "Business"),
        "FEATURE": ({"feature_name": "AI", "description": "智能写作"}, "AI"),
        "POSITIONING": ({"positioning": "团队协作工作区"}, "团队协作"),
        "PRODUCT_UPDATE": ({"title": "New API", "date": "2026-07-01"}, "New API"),
    }
    for category, (value, expected) in cases.items():
        displayed = formatter.format(category, value, fact_key="sample.key")
        assert expected in displayed
        assert not displayed.startswith("{")


def test_change_values_use_same_readable_format() -> None:
    formatter = FactDisplayFormatter()
    old, new = formatter.format_change(
        "PRICE",
        "price.plus",
        {"plan_name": "Plus", "amount": "10", "currency": "USD"},
        {"plan_name": "Plus", "amount": "12", "currency": "USD"},
    )
    assert old == "Plus：10 USD"
    assert new == "Plus：12 USD"


def test_price_decodes_legacy_double_encoded_json() -> None:
    value = json.dumps(json.dumps({
        "plan_name": "Plus",
        "amount": "12",
        "currency": "USD",
        "billing_period": "MONTH",
        "billing_unit": "USER",
    }))
    assert FactDisplayFormatter().format("PRICE", value) == (
        "Plus：12 USD / 用户 / 月"
    )

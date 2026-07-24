from competitive_intel.domain.facts import FactCategory
from competitive_intel.infrastructure.facts import (
    FactExtractionRequest, FixtureFactExtractionProvider,
)


def test_fixture_fact_provider_is_offline_bounded_and_structured() -> None:
    provider = FixtureFactExtractionProvider()
    response = provider.extract(
        FactExtractionRequest(
            "Notion", "PRICING", "https://www.notion.so/pricing", 10,
            "fixed clean content", (FactCategory.PLAN, FactCategory.PRICE),
            {}, 3,
        )
    )
    assert response.provider == "fixture"
    assert response.model == "fixture-v1"
    assert len(response.candidate_facts) == 3
    assert set(item.fact_category for item in response.candidate_facts) <= {
        FactCategory.PLAN, FactCategory.PRICE
    }
    assert response.usage["input_characters"] == len("fixed clean content")
    assert response.warnings == (
        "Fact limit reached; remaining fixture candidates were not returned.",
    )


def test_fixture_fact_provider_returns_structured_missing_page_error() -> None:
    response = FixtureFactExtractionProvider().extract(
        FactExtractionRequest(
            "Unknown", "HOMEPAGE", "https://unknown.example/", 1, "text",
            (FactCategory.POSITIONING,), {}, 5,
        )
    )
    assert response.candidate_facts == ()
    assert "No fact fixture" in (response.error or "")

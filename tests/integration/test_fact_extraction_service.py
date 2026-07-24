from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from competitive_intel.domain.facts import FactExtractionLimits
from competitive_intel.infrastructure.facts import FixtureFactExtractionProvider
from competitive_intel.infrastructure.http.fixture_fetcher import FixturePageFetcher
from competitive_intel.infrastructure.search.providers.fixture import FixtureSearchProvider
from competitive_intel.services.fact_extraction_service import FactExtractionService
from competitive_intel.services.snapshot_service import SnapshotService
from competitive_intel.services.source_discovery_service import SourceDiscoveryService


def _prepare_successful_snapshots(persistence, competitor_name: str = "Notion"):
    SourceDiscoveryService(
        persistence, FixtureSearchProvider(), FixturePageFetcher()
    ).discover(competitor_name)
    normalized = competitor_name.casefold()
    with persistence.transaction() as session:
        competitor = persistence.competitors.get_by_normalized_name(session, normalized)
        sources = persistence.sources.list_verified(session, competitor["id"])
        run_id = persistence.agent_runs.create(
            session,
            competitor_id=competitor["id"],
            input_name=competitor_name,
            normalized_input=normalized,
            run_mode="BASELINE",
            current_state="PAGE_FETCHING",
        )
    service = SnapshotService(persistence, FixturePageFetcher())
    for source in sources:
        service.process(source_id=source["id"], run_id=run_id)
    return competitor, sources


def test_extracts_evidence_bound_facts_and_records_audit(persistence) -> None:
    competitor, sources = _prepare_successful_snapshots(persistence)

    result = FactExtractionService(
        persistence, FixtureFactExtractionProvider()
    ).extract("Notion")

    assert result.candidate_count == 9
    assert len(result.saved) == 9
    assert not result.rejected
    assert {item.category.value for item in result.saved} == {
        "POSITIONING", "FEATURE", "PLAN", "PRICE", "PRODUCT_UPDATE"
    }
    price_keys = {item.fact_key for item in result.saved if item.category.value == "PRICE"}
    assert "price.plus.month.user.annual_billing" in price_keys
    assert "price.plus.month.user.monthly_billing" in price_keys
    with persistence.transaction() as session:
        facts = persistence.product_facts.list_for_run(session, result.run_id)
        run = persistence.agent_runs.get(session, result.run_id)
    assert len(facts) == 9
    assert all(item["evidence_status"] == "CONFIRMED" for item in facts)
    assert all(item["statement_type"] == "FACT" for item in facts)
    assert run["status"] == "COMPLETED"
    assert run["tool_call_count"] == len(sources)


def test_same_snapshots_are_idempotent_across_repeated_runs(persistence) -> None:
    _prepare_successful_snapshots(persistence)
    service = FactExtractionService(persistence, FixtureFactExtractionProvider())
    first = service.extract("Notion")
    second = service.extract("Notion")

    assert len(first.saved) == 9
    assert len(second.saved) == 0
    assert second.duplicate_count == 9
    with persistence.transaction() as session:
        competitor = persistence.competitors.get_by_normalized_name(session, "notion")
        sources = persistence.sources.list_verified(session, competitor["id"])
        count = sum(
            len(
                persistence.product_facts.list_for_snapshot(
                    session,
                    persistence.snapshots.get_latest_successful(
                        session, source["id"]
                    )["id"],
                )
            )
            for source in sources
        )
    assert count == 9


def test_no_successful_snapshot_skips_provider(persistence) -> None:
    SourceDiscoveryService(
        persistence, FixtureSearchProvider(), FixturePageFetcher()
    ).discover("Notion")
    provider = FixtureFactExtractionProvider()

    result = FactExtractionService(persistence, provider).extract("Notion")

    assert result.saved == ()
    assert provider.calls == []
    assert len(result.warnings) == 4


@pytest.mark.parametrize("fetch_status", ["FAILED", "JS_UNSUPPORTED"])
def test_failed_and_js_snapshots_are_never_extracted(
    persistence, fetch_status
) -> None:
    SourceDiscoveryService(
        persistence, FixtureSearchProvider(), FixturePageFetcher()
    ).discover("Notion")
    with persistence.transaction() as session:
        competitor = persistence.competitors.get_by_normalized_name(session, "notion")
        source = persistence.sources.list_verified(session, competitor["id"])[0]
        run_id = persistence.agent_runs.create(
            session,
            competitor_id=competitor["id"],
            input_name="Notion",
            normalized_input="notion",
            run_mode="BASELINE",
            current_state="PAGE_FETCHING",
        )
        persistence.snapshots.create(
            session,
            source_id=source["id"],
            run_id=run_id,
            requested_url=source["url"],
            fetch_status=fetch_status,
            fetched_at=datetime.now(UTC).replace(tzinfo=None),
            error_code=fetch_status,
        )
    provider = FixtureFactExtractionProvider()
    result = FactExtractionService(persistence, provider).extract("Notion")
    assert result.saved == ()
    assert provider.calls == []


class OnePageFailingProvider:
    name = "one-page-failing"

    def __init__(self):
        self.fixture = FixtureFactExtractionProvider()

    def extract(self, request):
        if request.source_type == "PRICING":
            raise RuntimeError("fixture pricing failure")
        return self.fixture.extract(request)


def test_single_page_failure_does_not_stop_other_pages(persistence) -> None:
    _prepare_successful_snapshots(persistence)
    result = FactExtractionService(
        persistence, OnePageFailingProvider()
    ).extract("Notion")

    assert len(result.saved) == 4
    assert any("pricing failure" in error for error in result.errors)
    assert {item.category.value for item in result.saved} == {
        "POSITIONING", "FEATURE", "PRODUCT_UPDATE"
    }


def test_fact_and_input_limits_are_enforced(persistence) -> None:
    _prepare_successful_snapshots(persistence)
    provider = FixtureFactExtractionProvider()
    result = FactExtractionService(
        persistence,
        provider,
        limits=FactExtractionLimits(
            max_facts_per_page=1,
            max_pages=4,
            max_input_characters=30,
            max_model_calls=2,
        ),
    ).extract("Notion")

    assert result.candidate_count == 2
    assert len(result.saved) == 2
    assert len(provider.calls) == 2
    assert all(len(call.clean_content) <= 30 for call in provider.calls)
    assert any("truncated" in warning for warning in result.warnings)
    assert "Model call limit reached." in result.warnings


class NoEvidenceProvider:
    name = "no-evidence"

    def extract(self, request):
        response = FixtureFactExtractionProvider().extract(request)
        return replace(
            response,
            candidate_facts=tuple(
                replace(item, evidence_text="Evidence does not exist.")
                for item in response.candidate_facts
            ),
        )


def test_facts_without_snapshot_evidence_are_not_persisted(persistence) -> None:
    _prepare_successful_snapshots(persistence)
    result = FactExtractionService(persistence, NoEvidenceProvider()).extract("Notion")

    assert result.saved == ()
    assert len(result.rejected) == 9
    assert all(item.status.value == "INSUFFICIENT_EVIDENCE" for item in result.rejected)
    assert all(
        item.candidate
        and item.candidate.competitor_id is not None
        and item.candidate.source_id is not None
        and item.candidate.snapshot_id is not None
        and item.candidate.source_url
        and item.candidate.evidence_status.value == "INSUFFICIENT_EVIDENCE"
        for item in result.rejected
    )
    with persistence.transaction() as session:
        assert persistence.product_facts.list_for_run(session, result.run_id) == []

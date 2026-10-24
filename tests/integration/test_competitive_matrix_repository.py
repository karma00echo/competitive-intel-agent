"""Existing 003 schema only; disposable MySQL and fixture page/fact providers."""

from types import SimpleNamespace

import pytest
import requests

from competitive_intel.domain.competitive_matrix import ResearchProduct
from competitive_intel.infrastructure.facts import FixtureFactExtractionProvider
from competitive_intel.infrastructure.http.fixture_fetcher import FixturePageFetcher
from competitive_intel.infrastructure.search.providers.fixture import FixtureSearchProvider
from competitive_intel.services.competitive_matrix_service import CompetitiveMatrixService
from competitive_intel.services.fact_extraction_service import FactExtractionService
from competitive_intel.services.snapshot_service import SnapshotService
from competitive_intel.services.source_discovery_service import SourceDiscoveryService

pytestmark = pytest.mark.integration


def test_repository_matrix_reads_observations_without_publishing_history(persistence, monkeypatch):
    monkeypatch.setattr(requests.Session, "request", lambda *a, **kw: pytest.fail("Live HTTP forbidden"))
    fetcher = FixturePageFetcher()
    SourceDiscoveryService(persistence, FixtureSearchProvider(), fetcher).discover("Notion")
    with persistence.transaction() as tx:
        product = persistence.competitors.get_by_normalized_name(tx, "notion")
        sources = persistence.sources.list_verified(tx, product["id"])
        run_id = persistence.agent_runs.create(tx, competitor_id=product["id"], input_name="Notion",
            normalized_input="notion", run_mode="UNKNOWN", current_state="PAGE_FETCHING")
    for source in sources:
        SnapshotService(persistence, fetcher).process(source_id=source["id"], run_id=run_id)
    result = FactExtractionService(persistence, FixtureFactExtractionProvider()).extract(
        "Notion", run_id=run_id, current_run_only=True)
    assert result.saved
    products = [ResearchProduct("Notion", product["id"], run_id, True)]
    task = SimpleNamespace(target="Notion", dimensions=["core_features", "pricing", "positioning"])
    service = CompetitiveMatrixService(persistence)
    first = service.build(task, products)
    assert first["facts"], first["gaps"]
    assert all(e["run_id"] == run_id and e["source_id"] in {s["id"] for s in sources}
               for e in first["evidence"].values())
    assert service.build(task, products) == first
    with persistence.transaction() as tx:
        observations = persistence.fact_observations.list_for_run(tx, run_id)
        current = persistence.fact_versions.list_current(tx, product["id"])
        run = persistence.agent_runs.get(tx, run_id)
    assert not current and all(o["comparison_status"] == "PENDING" for o in observations)
    assert run["run_mode"] == "UNKNOWN"
    # Deliberately incorrect run/product pairing must never borrow those observations.
    wrong = service.build(task, [ResearchProduct("Notion", product["id"] + 1, run_id, True)])
    assert not wrong["facts"]
    assert any(g["code"] == "PRODUCT_ATTRIBUTION_MISMATCH" for g in wrong["gaps"])

"""Phase-four offline fact-extraction demonstration (not the final Agent CLI)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from competitive_intel.config import Settings  # noqa: E402
from competitive_intel.infrastructure.facts import (  # noqa: E402
    FixtureFactExtractionProvider,
)
from competitive_intel.infrastructure.http.fixture_fetcher import (  # noqa: E402
    FixturePageFetcher,
)
from competitive_intel.infrastructure.search.providers.fixture import (  # noqa: E402
    FixtureSearchProvider,
)
from competitive_intel.persistence import Database, Persistence  # noqa: E402
from competitive_intel.services.fact_extraction_service import (  # noqa: E402
    FactExtractionService,
)
from competitive_intel.services.snapshot_service import SnapshotService  # noqa: E402
from competitive_intel.services.source_discovery_service import (  # noqa: E402
    SourceDiscoveryService,
)


def _prepare_fixture_snapshots(
    persistence: Persistence, competitor_name: str, language: str | None
) -> None:
    SourceDiscoveryService(
        persistence, FixtureSearchProvider(), FixturePageFetcher()
    ).discover(competitor_name, language=language)
    normalized = competitor_name.strip().casefold()
    with persistence.transaction() as session:
        competitor = persistence.competitors.get_by_normalized_name(
            session, normalized
        )
        if competitor is None:
            raise RuntimeError("Fixture source discovery did not verify a competitor.")
        sources = persistence.sources.list_verified(session, competitor["id"])
        missing = [
            source for source in sources
            if persistence.snapshots.get_latest_successful(session, source["id"]) is None
        ]
        if not missing:
            return
        run_id = persistence.agent_runs.create(
            session,
            competitor_id=competitor["id"],
            input_name=competitor_name,
            normalized_input=normalized,
            run_mode="BASELINE",
            current_state="PAGE_FETCHING",
        )
    snapshot_service = SnapshotService(persistence, FixturePageFetcher())
    for source in missing:
        snapshot_service.process(source_id=source["id"], run_id=run_id)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline phase-four structured fact extraction demo."
    )
    parser.add_argument("competitor")
    parser.add_argument("--provider", default="fixture")
    parser.add_argument("--language", default=None)
    args = parser.parse_args()
    if args.provider != "fixture":
        print(
            "Only fixture extraction is implemented in phase four. Add a "
            "FactExtractionProvider adapter for a real model.",
            file=sys.stderr,
        )
        return 2

    settings = Settings.from_env()
    persistence = Persistence(Database(settings.database))
    try:
        _prepare_fixture_snapshots(persistence, args.competitor, args.language)
        result = FactExtractionService(
            persistence, FixtureFactExtractionProvider()
        ).extract(args.competitor)
    except Exception as exc:
        print(f"Fact extraction failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        persistence.database.dispose()

    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if not result.errors else 3


if __name__ == "__main__":
    raise SystemExit(main())

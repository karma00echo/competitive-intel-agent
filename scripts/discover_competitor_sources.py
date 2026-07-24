"""Phase-three fixture demonstration entrypoint (not the final Agent CLI)."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from competitive_intel.config import Settings  # noqa: E402
from competitive_intel.infrastructure.http.fixture_fetcher import (  # noqa: E402
    FixturePageFetcher,
)
from competitive_intel.infrastructure.search.factory import (  # noqa: E402
    create_search_provider,
)
from competitive_intel.persistence import Database, Persistence  # noqa: E402
from competitive_intel.services.source_discovery_service import (  # noqa: E402
    SourceDiscoveryService,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Offline phase-three competitor source-discovery demo."
    )
    parser.add_argument("competitor")
    parser.add_argument("--provider", default="fixture")
    parser.add_argument("--locale", default=None)
    parser.add_argument("--language", default=None)
    args = parser.parse_args()

    if args.provider != "fixture":
        print(
            "Only fixture is implemented in phase three. Add a SearchProvider "
            "adapter before selecting a real provider.",
            file=sys.stderr,
        )
        return 2

    settings = Settings.from_env()
    try:
        persistence = Persistence(Database(settings.database))
        provider = create_search_provider("fixture")
        result = SourceDiscoveryService(
            persistence, provider, FixturePageFetcher()
        ).discover(
            args.competitor,
            locale=args.locale or ("zh-CN" if args.language == "zh" else "en-US"),
            language=args.language,
        )
    except Exception as exc:
        print(
            "Source discovery could not start. Check the disposable/application "
            f"MySQL configuration. {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1
    finally:
        if "persistence" in locals():
            persistence.database.dispose()

    print(json.dumps(asdict(result), ensure_ascii=False, indent=2))
    return 0 if not result.errors else 3


if __name__ == "__main__":
    raise SystemExit(main())

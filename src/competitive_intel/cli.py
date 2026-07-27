"""Minimal unified CLI for the controlled phase-five Agent Runner."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from typing import Sequence

from competitive_intel.config import Settings
from competitive_intel.domain.agent import AgentRunnerLimits, AgentState
from competitive_intel.infrastructure.agent import FixtureAgentProvider
from competitive_intel.infrastructure.facts import FixtureFactExtractionProvider
from competitive_intel.infrastructure.http.fixture_fetcher import FixturePageFetcher
from competitive_intel.infrastructure.search.factory import create_search_provider
from competitive_intel.persistence import Database, Persistence
from competitive_intel.services import (
    AgentRunner,
    AgentToolExecutor,
    FactExtractionService,
    SnapshotService,
    SourceDiscoveryService,
)


class CLIArgumentError(ValueError):
    pass


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise CLIArgumentError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(prog="competitive-intel")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("competitor")
    analyze.add_argument("--search-provider", default="fixture")
    analyze.add_argument("--fact-provider", default="fixture")
    analyze.add_argument("--agent-provider", default="fixture")
    analyze.add_argument("--language", default=None)
    analyze.add_argument("--locale", default="en-US")
    analyze.add_argument("--verbose", action="store_true")
    analyze.add_argument("--max-tool-calls", type=int, default=12)
    return parser


def _fixture_only(value: str, kind: str) -> None:
    if value.strip().casefold() != "fixture":
        raise CLIArgumentError(
            f"{kind} provider {value!r} is not implemented; use fixture."
        )


def exit_code_for_state(state: AgentState) -> int:
    if state == AgentState.COMPLETED:
        return 0
    if state == AgentState.COMPLETED_WITH_WARNINGS:
        return 2
    return 1


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = build_parser().parse_args(argv)
        if args.max_tool_calls < 1:
            raise CLIArgumentError("--max-tool-calls must be at least 1.")
        _fixture_only(args.fact_provider, "fact")
        _fixture_only(args.agent_provider, "agent")
        search_provider = create_search_provider(args.search_provider)
    except (CLIArgumentError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 64

    settings = Settings.from_env()
    database = Database(settings.database)
    persistence = Persistence(database)

    def emit(event: dict) -> None:
        if args.verbose:
            print(json.dumps(event, ensure_ascii=False, default=str))

    try:
        fetcher = FixturePageFetcher()
        source_service = SourceDiscoveryService(
            persistence, search_provider, fetcher
        )
        snapshot_service = SnapshotService(persistence, fetcher)
        fact_service = FactExtractionService(
            persistence, FixtureFactExtractionProvider()
        )
        tools = AgentToolExecutor(
            persistence, source_service, snapshot_service, fact_service
        )
        runner = AgentRunner(
            persistence,
            FixtureAgentProvider(),
            tools,
            limits=AgentRunnerLimits(max_tool_calls=args.max_tool_calls),
            event_sink=emit,
        )
        result = runner.run(
            args.competitor, locale=args.locale, language=args.language
        )
    except (ValueError, RuntimeError) as exc:
        print(f"Configuration error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 64
    except Exception as exc:
        print(f"Agent run failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        database.dispose()

    payload = (
        asdict(result.summary)
        if result.summary is not None
        else {
            "run_id": result.run_id,
            "run_mode": result.run_mode,
            "final_state": result.final_state,
            "tool_call_count": result.tool_call_count,
            "warnings": result.warnings,
            "errors": result.errors,
        }
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return exit_code_for_state(result.final_state)


if __name__ == "__main__":
    raise SystemExit(main())

"""Minimal unified CLI for the controlled phase-five Agent Runner."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Sequence

from competitive_intel.config import Settings
from competitive_intel.domain.agent import AgentRunnerLimits, AgentState
from competitive_intel.infrastructure.agent import FixtureAgentProvider
from competitive_intel.infrastructure.facts import FixtureFactExtractionProvider
from competitive_intel.infrastructure.http.fixture_fetcher import FixturePageFetcher
from competitive_intel.infrastructure.http.requests_fetcher import RequestsFetcher
from competitive_intel.infrastructure.search.factory import create_search_provider
from competitive_intel.persistence import Database, Persistence
from competitive_intel.services import (
    AgentRunner,
    AgentToolExecutor,
    FactExtractionService,
    SnapshotService,
    SourceDiscoveryService,
    CompetitorReportService,
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
    analyze.add_argument("--skip-fact-extraction", action="store_true")
    analyze.add_argument(
        "--fixture-scenario",
        choices=(
            "unchanged",
            "price_changed",
            "feature_added",
            "feature_removed",
            "page_failure",
        ),
        default="unchanged",
    )
    report = subparsers.add_parser("report")
    report_commands = report.add_subparsers(
        dest="report_command", required=True
    )
    show = report_commands.add_parser("show")
    show.add_argument("--report-id", type=int)
    show.add_argument("--run-id", type=int)
    show.add_argument("--competitor")
    show.add_argument("--latest", action="store_true")
    export = report_commands.add_parser("export")
    export.add_argument("--report-id", type=int)
    export.add_argument("--run-id", type=int)
    export.add_argument("--competitor")
    export.add_argument("--latest", action="store_true")
    export.add_argument(
        "--format", choices=("markdown", "json"), required=True
    )
    export.add_argument("--output", required=True)
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
        settings = Settings.from_env()
        if args.command == "analyze" and args.max_tool_calls < 1:
            raise CLIArgumentError("--max-tool-calls must be at least 1.")
        if args.command == "analyze":
            _fixture_only(args.fact_provider, "fact")
            _fixture_only(args.agent_provider, "agent")
            search_provider = create_search_provider(
                args.search_provider,
                api_key=settings.search.api_key,
                endpoint=settings.search.endpoint,
            )
        elif args.command == "report":
            selectors = sum(
                (
                    args.report_id is not None,
                    args.run_id is not None,
                    bool(args.competitor and args.latest),
                )
            )
            if selectors != 1:
                raise CLIArgumentError(
                    f"report {args.report_command} requires exactly one of --report-id, "
                    "--run-id, or --competitor with --latest."
                )
    except (CLIArgumentError, ValueError) as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 64

    database = Database(settings.database)
    persistence = Persistence(database)

    if args.command == "report":
        try:
            reports = CompetitorReportService(persistence)
            report = reports.get(
                report_id=getattr(args, "report_id", None),
                run_id=getattr(args, "run_id", None),
                competitor_name=getattr(args, "competitor", None),
                latest=getattr(args, "latest", False),
            )
            if report is None:
                print("Report not found.", file=sys.stderr)
                return 1
            if args.report_command == "show":
                print(
                    json.dumps(
                        {
                            "report_id": report.report_id,
                            "report_type": report.report_type,
                            "title": report.title,
                            "executive_summary": report.executive_summary,
                            "change_summary": report.change_summary,
                            "content_json": report.content_json,
                            "content_markdown": report.content_markdown,
                        },
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )
                )
            else:
                output = Path(args.output).resolve()
                output.parent.mkdir(parents=True, exist_ok=True)
                content = (
                    report.content_markdown
                    if args.format == "markdown"
                    else json.dumps(
                        report.content_json,
                        ensure_ascii=False,
                        indent=2,
                        default=str,
                    )
                    + "\n"
                )
                output.write_text(content, encoding="utf-8")
                print(
                    json.dumps(
                        {
                            "report_id": report.report_id,
                            "format": args.format,
                            "output": str(output),
                        },
                        ensure_ascii=False,
                    )
                )
            return 0
        except (OSError, ValueError) as exc:
            print(f"Report command failed: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        finally:
            database.dispose()

    def emit(event: dict) -> None:
        if args.verbose:
            print(json.dumps(event, ensure_ascii=False, default=str))

    try:
        real_search = search_provider.name != "fixture"
        skip_fact_extraction = (
            args.skip_fact_extraction or real_search
        )
        fetcher = (
            RequestsFetcher()
            if real_search
            else FixturePageFetcher(scenario=args.fixture_scenario)
        )
        source_service = SourceDiscoveryService(
            persistence, search_provider, fetcher
        )
        snapshot_service = SnapshotService(persistence, fetcher)
        fact_service = FactExtractionService(
            persistence,
            FixtureFactExtractionProvider(scenario=args.fixture_scenario),
        )
        tools = AgentToolExecutor(
            persistence,
            source_service,
            snapshot_service,
            fact_service,
            skip_fact_extraction=skip_fact_extraction,
            search_provider=search_provider.name,
            fetch_mode="real" if real_search else "fixture",
            agent_provider="fixture",
            fact_provider="fixture",
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
    if payload.get("report_id") is not None:
        payload["report_view_command"] = (
            f'"{sys.executable}" -m competitive_intel.cli report show '
            f"--report-id {payload['report_id']}"
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return exit_code_for_state(result.final_state)


if __name__ == "__main__":
    raise SystemExit(main())

"""Bounded in-process analysis execution for the local console."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from typing import Callable

from competitive_intel.api.schemas import AnalysisRequest
from competitive_intel.config import Settings
from competitive_intel.domain.agent import AgentRunnerLimits
from competitive_intel.domain.names import normalize_competitor_name
from competitive_intel.infrastructure.agent import FixtureAgentProvider
from competitive_intel.infrastructure.facts import FixtureFactExtractionProvider
from competitive_intel.infrastructure.http.fixture_fetcher import FixturePageFetcher
from competitive_intel.infrastructure.http.requests_fetcher import RequestsFetcher
from competitive_intel.infrastructure.search.factory import create_search_provider
from competitive_intel.persistence import Persistence
from competitive_intel.services import (
    AgentRunner,
    AgentToolExecutor,
    FactExtractionService,
    SnapshotService,
    SourceDiscoveryService,
)


class AnalysisAlreadyRunning(RuntimeError):
    pass


class AnalysisCapacityReached(RuntimeError):
    pass


class AnalysisStartFailed(RuntimeError):
    pass


RunnerBuilder = Callable[[AnalysisRequest, Callable[[dict], None]], AgentRunner]


def build_runner(
    settings: Settings,
    persistence: Persistence,
    request: AnalysisRequest,
    event_sink: Callable[[dict], None],
) -> AgentRunner:
    search = create_search_provider(
        request.search_provider,
        api_key=settings.search.api_key,
        endpoint=settings.search.endpoint,
    )
    real_search = search.name != "fixture"
    scenario = "unchanged" if request.fixture_scenario == "default" else request.fixture_scenario
    fetcher = RequestsFetcher() if real_search else FixturePageFetcher(scenario=scenario)
    source_service = SourceDiscoveryService(persistence, search, fetcher)
    snapshot_service = SnapshotService(persistence, fetcher)
    fact_service = FactExtractionService(
        persistence, FixtureFactExtractionProvider(scenario=scenario)
    )
    tools = AgentToolExecutor(
        persistence,
        source_service,
        snapshot_service,
        fact_service,
        skip_fact_extraction=request.skip_fact_extraction or real_search,
        search_provider=search.name,
        fetch_mode="real" if real_search else "fixture",
        agent_provider=request.agent_provider,
        fact_provider=request.fact_provider,
    )
    return AgentRunner(
        persistence,
        FixtureAgentProvider(),
        tools,
        limits=AgentRunnerLimits(max_tool_calls=request.max_tool_calls),
        event_sink=event_sink,
    )


class AnalysisTaskManager:
    """Fixed-size executor with one active task per normalized competitor."""

    def __init__(
        self,
        persistence: Persistence,
        runner_builder: RunnerBuilder,
        *,
        max_workers: int = 2,
    ) -> None:
        self._persistence = persistence
        self._builder = runner_builder
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="competitive-analysis"
        )
        self._max_workers = max_workers
        self._lock = Lock()
        self._active: set[str] = set()

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)

    def start(self, request: AnalysisRequest) -> int:
        normalized = normalize_competitor_name(request.competitor_name).normalized_name
        with self._lock:
            if normalized in self._active:
                raise AnalysisAlreadyRunning(normalized)
            if len(self._active) >= self._max_workers:
                raise AnalysisCapacityReached("Global analysis capacity reached.")
            self._active.add(normalized)

        started = Event()
        holder: dict[str, object] = {}

        def sink(event: dict) -> None:
            if event.get("event") == "run_started":
                holder["run_id"] = int(event["run_id"])
                started.set()

        try:
            self._executor.submit(self._execute, request, normalized, sink, holder, started)
        except Exception:
            with self._lock:
                self._active.discard(normalized)
            raise
        if not started.wait(timeout=5):
            raise AnalysisStartFailed(
                str(holder.get("error") or "Timed out while creating the analysis run.")
            )
        if "error" in holder and "run_id" not in holder:
            raise AnalysisStartFailed(str(holder["error"]))
        return int(holder["run_id"])

    def _execute(
        self,
        request: AnalysisRequest,
        normalized: str,
        sink: Callable[[dict], None],
        holder: dict[str, object],
        started: Event,
    ) -> None:
        try:
            runner = self._builder(request, sink)
            runner.run(
                request.competitor_name,
                locale=request.locale,
                language=request.language,
            )
        except Exception as exc:
            holder["error"] = f"{type(exc).__name__}: {exc}"
            run_id = holder.get("run_id")
            if run_id is not None:
                try:
                    with self._persistence.transaction() as session:
                        self._persistence.agent_runs.finish(
                            session,
                            int(run_id),
                            status="FAILED",
                            current_state="FAILED",
                            error_code="BACKGROUND_TASK_EXCEPTION",
                            error_message=str(exc)[:1000],
                        )
                except Exception:
                    pass
            started.set()
        finally:
            with self._lock:
                self._active.discard(normalized)

    def shutdown(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

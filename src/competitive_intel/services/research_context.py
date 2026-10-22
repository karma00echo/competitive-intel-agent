"""Task-scoped provider factory used by discovery and subsequent research tools."""

from dataclasses import asdict, replace
from urllib.parse import urlsplit

from competitive_intel.domain.task_budget import TaskBudget
from competitive_intel.infrastructure.agent.task_understanding import LLMTaskUnderstandingProvider
from competitive_intel.infrastructure.agent.candidate_evaluation import CandidateEvaluator
from competitive_intel.infrastructure.budgeted_transport import BudgetedSession, CostRates
from competitive_intel.infrastructure.facts.llm_provider import LLMFactExtractionProvider
from competitive_intel.infrastructure.http.requests_fetcher import RequestsFetcher
from competitive_intel.infrastructure.search.providers.serper import SerperSearchProvider, DEFAULT_SERPER_ENDPOINT


class ResearchContext:
    """Never create a new context per product. Rehydrate only trusted stored audit.

    Existing FactExtractionService caches remain authoritative: a cache hit never
    reaches the model transport and therefore consumes no model/token reservation.
    """

    def __init__(self, settings, *, allow_paid=False, budget=None, rates=None, session_factory=None):
        self.settings = settings
        self.allow_paid = allow_paid
        self.budget = budget or TaskBudget()
        if allow_paid and session_factory is None and rates is None:
            raise ValueError("Explicit reviewed cost rates required for live providers")
        self.rates = rates or CostRates()
        self._factory = session_factory
        self._sessions = []

    def session(self, purpose):
        if not self.allow_paid:
            raise PermissionError("Explicit paid provider consent is required")
        transport = BudgetedSession(self.budget, purpose, rates=self.rates,
                                    session=self._factory(purpose) if self._factory else None)
        self._sessions.append(transport)
        return transport

    def audit_policy(self):
        return {"cost_rates": asdict(self.rates), "model": self.settings.llm.model,
                "model_endpoint_host": urlsplit(self.settings.llm.endpoint or "").hostname,
                "transport_mode": "injected" if self._factory else "live",
                "cost_semantics": "conservative_reserved_micro_usd_not_invoice"}

    @classmethod
    def from_trusted_audit(cls, settings, audit, *, allow_paid=False, session_factory=None):
        policy = audit["research_policy"]
        if (policy["model"] != settings.llm.model or policy["model_endpoint_host"] !=
                urlsplit(settings.llm.endpoint or "").hostname):
            raise ValueError("Cannot change model billing policy within an existing task")
        return cls(settings, allow_paid=allow_paid, budget=TaskBudget.from_trusted_state(audit["budget"]),
                   rates=CostRates(**policy["cost_rates"]), session_factory=session_factory)

    def search_provider(self):
        return SerperSearchProvider(self.settings.search.api_key,
                                    endpoint=self.settings.search.endpoint or DEFAULT_SERPER_ENDPOINT,
                                    session=self.session("searches"), max_attempts=1)

    def page_fetcher(self):
        return RequestsFetcher(session=self.session("fetches"))

    def understanding_provider(self):
        return LLMTaskUnderstandingProvider(self.settings.llm, session=self.session("understanding"))

    def candidate_evaluator(self):
        return CandidateEvaluator(self.settings.llm, self.session("evaluation"))

    def fact_provider(self):
        return LLMFactExtractionProvider(replace(self.settings.llm, max_calls=10, max_retries=0),
                                         session=self.session("extraction"))

    def research_services(self, persistence):
        """Handoff for later research: all three reuse this ledger across products.

        Does not start research or historical baseline publication.
        """
        from .source_discovery_service import SourceDiscoveryService
        from .snapshot_service import SnapshotService
        from .fact_extraction_service import FactExtractionService
        search, fetcher = self.search_provider(), self.page_fetcher()
        return (SourceDiscoveryService(persistence, search, fetcher),
                SnapshotService(persistence, fetcher), FactExtractionService(persistence, self.fact_provider()))

    def close(self):
        for session in self._sessions:
            session.close()

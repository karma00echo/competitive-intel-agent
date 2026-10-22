"""Synthetic HTTP only: exercises production search/fetch/evaluation adapters."""

from dataclasses import replace
import json

from competitive_intel.config import DatabaseSettings, Settings, SearchSettings, LLMSettings
from competitive_intel.domain.analysis_task import AnalysisTaskSpec, DEFAULT_DIMENSIONS
from competitive_intel.domain.task_budget import TaskBudget
from competitive_intel.services.competitor_discovery import CompetitorDiscoveryService
from competitive_intel.services.research_context import ResearchContext


def spec(**kwargs):
    return AnalysisTaskSpec(**(dict(status="READY", target="Atlas", intent="competitive_analysis",
        competitors=[], dimensions=list(DEFAULT_DIMENSIONS), output_format="report", discover_competitors=True,
        assumptions=[], clarification=None) | kwargs))


def settings():
    return Settings(DatabaseSettings("127.0.0.1", 3306, "unused_test", "unused", ""),
                    search=SearchSettings("serper", "offline-search-key"),
                    llm=LLMSettings(api_key="offline-model-key", model="test-model", endpoint="https://models.example"))


class Response:
    def __init__(self, data=None, *, html=None, url="https://example.org/", status=200, headers=None):
        self.content = (html if html is not None else json.dumps(data)).encode()
        self.url, self.status_code = url, status
        self.headers = headers or {"Content-Type": "text/html" if html is not None else "application/json"}
        self.history = []
        self.encoding = "utf-8"
        self.closed = False

    def json(self): return json.loads(self.content)
    def iter_content(self, chunk_size=8192): yield self.content
    def close(self): self.closed = True
    def __enter__(self): return self
    def __exit__(self, *args): self.close()


class Transport:
    def __init__(self, *, mode="normal", candidates=("Birch", "Cedar", "Dune")):
        self.mode, self.candidates = mode, candidates
        self.calls = []

    def close(self): pass

    def post(self, url, **kwargs):
        payload = kwargs["json"]
        self.calls.append(("post", url, payload))
        if "q" in payload:
            if self.mode == "search_failure":
                return Response({}, status=503)
            query = payload["q"]
            name = query.split('"')[1]
            if "alternatives competitors" in query:
                names = self.candidates
                if self.mode == "article":
                    return Response({"organic": [{"title": "Best alternatives", "link": "https://guide.example/", "snippet": "A guide"}]})
            else:
                names = (name,)
            rows = [{"title": n + " | Product", "link": f"https://{n.lower()}.example/",
                     "snippet": n + " product features", "position": i + 1} for i, n in enumerate(names)]
            if self.mode == "ambiguous" and name == "Atlas":
                rows.append(dict(rows[0], link="https://atlas-other.example/"))
            return Response({"organic": rows})
        if self.mode == "model_failure":
            return Response({}, status=503)
        supplied = json.loads(payload["messages"][-1]["content"])
        if "request" in supplied:
            answer = spec().model_dump()
        else:
            answer = {"candidates": [{"name": c["name"], "target_quote": "Atlas provides document collaboration for teams.",
                       "candidate_quote": c["name"] + " provides document collaboration for teams.",
                       "shared_use": "document collaboration"} for c in supplied["candidates"]]}
            if self.mode == "unrelated": answer = {"candidates": []}
            if self.mode == "fabricated_quote": answer["candidates"][0]["candidate_quote"] += " fabricated"
            if self.mode == "invented_name": answer["candidates"][0]["name"] = "Invented"
        return Response({"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(answer)}}],
                         "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80}})

    def get(self, url, **kwargs):
        self.calls.append(("get", url, kwargs))
        if self.mode == "page_failure":
            return Response({}, url=url, status=403)
        if url == "https://guide.example/":
            return Response(html='<html><article><p>Alternatives guide.</p>' + ''.join(
                f'<a href="https://{n.lower()}.example/">{n}</a>' for n in self.candidates) + '</article></html>', url=url)
        name = url.split("//")[1].split(".")[0].replace("-other", "").title()
        html = (f'<html><head><title>{name}</title><link rel="canonical" href="{url}"/>'
                f'<meta property="og:site_name" content="{name}"/></head><body><main>'
                f'<h1>{name}</h1><p>{name} provides document collaboration for teams.</p>'
                f'<a href="/features">Features</a><a href="/pricing">Pricing</a></main><footer>Copyright {name}</footer></body></html>')
        return Response(html=html, url=url)


def service(*, limits=None, mode="normal", candidates=("Birch", "Cedar", "Dune")):
    transport = Transport(mode=mode, candidates=candidates)
    context = ResearchContext(settings(), allow_paid=True, budget=TaskBudget(limits), session_factory=lambda purpose: transport)
    value = CompetitorDiscoveryService(context, context.search_provider(), context.page_fetcher(), context.candidate_evaluator())
    return value, transport

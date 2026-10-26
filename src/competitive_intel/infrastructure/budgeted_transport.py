"""Budget enforcement below providers, including retries and redirect hops."""

import json
import os
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import requests


@dataclass(frozen=True)
class CostRates:
    # Explicit deployment ceilings in micro-USD, not live pricing or invoices.
    search: int = 1_000
    input_per_million: int = 300_000
    output_per_million: int = 1_200_000

    def __post_init__(self):
        if any(type(v) is not int or v < 0 for v in vars(self).values()):
            raise ValueError("Invalid rates")

    @classmethod
    def from_env(cls):
        """Operator-reviewed prices, never guess prices for an arbitrary endpoint."""
        names = ("RESEARCH_SEARCH_COST_MICROUSD", "RESEARCH_INPUT_COST_MICROUSD_PER_MILLION",
                 "RESEARCH_OUTPUT_COST_MICROUSD_PER_MILLION")
        values = [os.getenv(name, "") for name in names]
        if not all(v.isdecimal() and int(v) > 0 for v in values):
            raise ValueError("RESEARCH_COST_RATES_REQUIRED")
        return cls(*(int(v) for v in values))


class BudgetedSession:
    def __init__(self, budget, kind, *, session=None, rates=None):
        if kind not in {"searches", "fetches", "understanding", "evaluation", "extraction", "synthesis"}:
            raise ValueError("Unknown budget purpose")
        self.budget, self.kind = budget, kind
        if session is None and kind == "fetches":
            from .http.public_session import PublicSession
            session = PublicSession()
        self.session = session or requests.Session()
        self.rates = rates or CostRates()

    def post(self, url, **kwargs):
        if self.kind == "searches":
            self.budget.reserve(searches=1, cost_microusd=self.rates.search)
        elif self.kind != "fetches":
            payload = kwargs.get("json", {})
            output = payload.get("max_tokens")
            if type(output) is not int or output <= 0:
                raise ValueError("A bounded model output is required")
            # UTF-8 bytes plus framing reserve is a conservative token estimate
            # for supported byte-tokenized chat models. Never refund unknown usage.
            inputs = len(json.dumps(payload, ensure_ascii=False).encode("utf-8")) + 1024
            cost = (inputs * self.rates.input_per_million + output * self.rates.output_per_million + 999_999) // 1_000_000
            self.budget.reserve(models=1, **{self.kind: 1}, tokens=inputs + output, cost_microusd=cost)
        else:
            raise ValueError("Fetch transport requires GET")
        # Search and model endpoints must not silently redirect around accounting.
        kwargs["allow_redirects"] = False
        return self.session.post(url, **kwargs)

    def get(self, url, **kwargs):
        if self.kind != "fetches":
            raise ValueError("Only fetch transport supports GET")
        follow = kwargs.pop("allow_redirects", True)
        history = []
        for _ in range(6):
            if urlsplit(url).scheme not in {"https", "http"}:
                raise requests.exceptions.InvalidURL("Only public web URL schemes are supported")
            self.budget.reserve(fetches=1)
            response = self.session.get(url, allow_redirects=False, **kwargs)
            if not follow or response.status_code not in {301, 302, 303, 307, 308} or not response.headers.get("Location"):
                response.history = history
                return response
            history.append(response)
            url = urljoin(url, response.headers["Location"])
            response.close()
        raise requests.exceptions.TooManyRedirects("Bounded redirect limit reached")

    def close(self):
        self.session.close()

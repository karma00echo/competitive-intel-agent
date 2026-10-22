"""One monotonic ledger for a whole research task, including failed attempts."""

from dataclasses import asdict, dataclass
from threading import RLock
from uuid import uuid4


class BudgetExhausted(RuntimeError):
    def __init__(self, resource):
        self.resource = resource
        super().__init__(f"TASK_BUDGET_EXHAUSTED:{resource}")


@dataclass(frozen=True)
class BudgetLimits:
    searches: int = 18
    fetches: int = 24
    models: int = 13
    understanding: int = 1
    evaluation: int = 1
    extraction: int = 10
    synthesis: int = 1
    tokens: int = 250_000
    cost_microusd: int = 1_000_000

    def __post_init__(self):
        if any(type(v) is not int or v < 0 for v in asdict(self).values()):
            raise ValueError("Budgets must be nonnegative integers")


class TaskBudget:
    """Reservations are never refunded: missing usage/errors cannot restore quota.

    Tokens/cost are conservative reservations, NOT measured provider usage.
    State is restored only from trusted server audit, never client-supplied counters.
    """

    def __init__(self, limits=None):
        self.limits = limits or BudgetLimits()
        self.task_id = uuid4().hex
        self.used = dict.fromkeys(asdict(self.limits), 0)
        self.exhausted = None
        self.events = []
        self.checkpoint = None
        self._lock = RLock()

    def reserve(self, **amounts):
        with self._lock:
            if self.exhausted:
                raise BudgetExhausted(self.exhausted)
            for name, amount in amounts.items():
                if name not in self.used or type(amount) is not int or amount < 0:
                    raise ValueError("Invalid reservation")
                if self.used[name] + amount > getattr(self.limits, name):
                    self.exhausted = name
                    self.events.append({"event": "denied", "resource": name})
                    if self.checkpoint:
                        self.checkpoint(self.snapshot())
                    raise BudgetExhausted(name)
            for name, amount in amounts.items():
                self.used[name] += amount
            self.events.append({"event": "reserved", **amounts})
            if self.checkpoint:
                self.checkpoint(self.snapshot())

    def snapshot(self):
        with self._lock:
            return {"version": 1, "task_id": self.task_id, "limits": asdict(self.limits),
                    "used": dict(self.used), "exhausted": self.exhausted,
                    "events": [dict(e) for e in self.events]}

    @classmethod
    def from_trusted_state(cls, state):
        if state.get("version") != 1:
            raise ValueError("Unknown ledger version")
        result = cls(BudgetLimits(**state["limits"]))
        if set(state["used"]) != set(result.used):
            raise ValueError("Incomplete ledger")
        for key, value in state["used"].items():
            if type(value) is not int or not 0 <= value <= getattr(result.limits, key):
                raise ValueError("Invalid ledger")
        result.task_id = state["task_id"]
        result.used = dict(state["used"])
        result.exhausted = state["exhausted"]
        result.events = [dict(e) for e in state["events"]]
        return result

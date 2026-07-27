"""Provider-neutral native tool-calling contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from competitive_intel.domain.agent import AgentState


@dataclass(frozen=True, slots=True)
class AgentToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AgentProviderRequest:
    system_instructions: str
    conversation_messages: tuple[dict[str, Any], ...]
    current_state: AgentState
    allowed_tools: tuple[str, ...]
    tool_schemas: tuple[dict[str, Any], ...]
    remaining_tool_budget: int
    run_context: dict[str, Any]


@dataclass(frozen=True, slots=True)
class AgentProviderResponse:
    assistant_message: str
    tool_calls: tuple[AgentToolCall, ...]
    provider: str
    model: str
    request_id: str
    usage: dict[str, int]
    warnings: tuple[str, ...] = ()
    error: str | None = None


class AgentProvider(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def model(self) -> str: ...

    def choose_tools(
        self, request: AgentProviderRequest
    ) -> AgentProviderResponse: ...

"""Stage 9.2.1: no DB, web fetching, search or real model calls."""

from dataclasses import replace
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import requests

from competitive_intel.api.task_understanding import router
from competitive_intel.cli import main
from competitive_intel.config import LLMSettings
from competitive_intel.domain.analysis_task import DEFAULT_DIMENSIONS
from competitive_intel.infrastructure.agent.task_understanding import (
    FixtureTaskUnderstandingProvider, LLMTaskUnderstandingProvider,
)
from competitive_intel.services.task_understanding_service import TaskUnderstandingService
from competitive_intel.web.intelligence import parse_analyst_command


@pytest.fixture(autouse=True)
def forbid_network(monkeypatch):
    def fail(*args, **kwargs):
        pytest.fail("Real HTTP is forbidden in task-understanding tests")
    monkeypatch.setattr(requests.Session, "request", fail)


def plan(**changes):
    value = dict(status="READY", target="豆包", intent="competitive_analysis",
                 competitors=[], dimensions=list(DEFAULT_DIMENSIONS), output_format="report",
                 discover_competitors=True, assumptions=["未指定竞品，后续自动发现。"], clarification=None)
    value.update(changes)
    return value


def config(**changes):
    return replace(LLMSettings(api_key="test-only-task-key", model="test-model",
                              endpoint="https://api.deepseek.com"), **changes)


class Response:
    def __init__(self, payload=None, *, status=200, finish="stop", usage=None):
        self.status_code = status
        self.closed = False
        self.body = json.dumps({"choices": [{"finish_reason": finish, "message": {
            "content": json.dumps(plan() if payload is None else payload, ensure_ascii=False)}}],
            "usage": usage}).encode()

    def __enter__(self): return self

    def __exit__(self, *args): self.closed = True

    def iter_content(self, size): yield self.body


class Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.parametrize("text,target,competitors,dimensions,form,intent", [
    ("分析豆包", "豆包", [], DEFAULT_DIMENSIONS, "report", "competitive_analysis"),
    ("帮我分析豆包及其主要竞争对手。", "豆包", [], DEFAULT_DIMENSIONS, "report", "competitive_analysis"),
    ("比较豆包和 Kimi", "豆包", ["Kimi"], DEFAULT_DIMENSIONS, "report", "comparison"),
    ("分析豆包的核心功能和定价策略", "豆包", [], ["core_features", "pricing"], "report", "competitive_analysis"),
    ("请用表格比较豆包和 Kimi 的定价及功能。", "豆包", ["Kimi"], ["core_features", "pricing"], "table", "comparison"),
    ("只分析豆包，不比较其他产品", "豆包", [], DEFAULT_DIMENSIONS, "report", "product_analysis"),
    ("简要分析 Acme Cloud 的目标用户", "Acme Cloud", [], ["target_users"], "brief", "competitive_analysis"),
])
def test_offline_examples(text, target, competitors, dimensions, form, intent):
    result = TaskUnderstandingService(FixtureTaskUnderstandingProvider()).interpret(text)
    assert result["status"] == "READY"
    task = result["task"]
    assert (task["target"], task["competitors"], task["dimensions"], task["output_format"], task["intent"]) == (
        target, competitors, dimensions, form, intent)
    assert task["discover_competitors"] == (not competitors and intent != "product_analysis")
    assert result["audit"]["attempts"] == 0
    assert result["audit"]["usage"] is None
    assert result["audit"]["execution_started"] is False


@pytest.mark.parametrize("text", ["分析它", "分析苹果", "比较豆包", "比较 A 和 B 和 C 和 D",
                                        "分析豆包的市场占有率", "只分析豆包和 Kimi", "分析",
                                        "分析豆包并输出表格"])
def test_ambiguity_and_out_of_scope_dimensions_are_not_silently_guessed(text):
    result = TaskUnderstandingService(FixtureTaskUnderstandingProvider()).interpret(text)
    assert result["status"] == "NEEDS_CLARIFICATION"
    assert result["task"]["clarification"]
    assert result["audit"]["execution_started"] is False


def test_production_adapter_interprets_free_language_using_structured_model_response():
    text = "我在给写作团队选工具，拿豆包跟 Kimi 看看，重点是面向谁和收费方式；给我一张表，不要再加其他产品。"
    response = Response(plan(intent="comparison", competitors=["Kimi"], discover_competitors=False,
                             dimensions=["target_users", "pricing"], output_format="table"),
                        usage={"prompt_tokens": 200, "completion_tokens": 100, "total_tokens": 300})
    session = Session(response)
    result = TaskUnderstandingService(LLMTaskUnderstandingProvider(config(), session=session)).interpret(text)
    assert result["status"] == "READY"
    assert result["task"]["dimensions"] == ["target_users", "pricing"]
    assert result["audit"]["usage"]["total_tokens"] == 300
    url, request = session.calls[0]
    assert url == "https://api.deepseek.com/chat/completions"
    assert request["json"]["thinking"] == {"type": "disabled"}
    assert request["json"]["max_tokens"] == 1500
    assert "tools" not in request["json"]
    assert json.loads(request["json"]["messages"][1]["content"])["request"] == text
    assert "JSON Schema" in request["json"]["messages"][0]["content"]
    assert request["allow_redirects"] is False
    assert request["timeout"] == (10, 45)
    assert config().api_key not in json.dumps(result)
    assert response.closed


@pytest.mark.parametrize("payload", [
    plan(competitors=["Kimi"], intent="comparison", discover_competitors=False),
    plan(target="ChatGPT"), plan(target="帮我分析豆包及其主要竞争对手"), plan(target="分析豆包"),
    plan(competitors=["豆包"], discover_competitors=False),
    plan(dimensions=[]), plan(dimensions=["market_share"]), plan(dimensions=["pricing", "pricing"]),
    plan(confidence=0.99), plan(intent="execute_sql"), plan(discover_competitors="yes"),
    plan(status="NEEDS_CLARIFICATION", clarification=None),
    plan(intent="comparison"), plan(intent="product_analysis"),
    plan(source_url="https://invented.example"), plan(facts=["豆包是免费的"]),
])
def test_untrusted_model_spec_is_rejected_without_execution(payload):
    session = Session(Response(payload))
    result = TaskUnderstandingService(LLMTaskUnderstandingProvider(config(), session=session)).interpret("分析豆包")
    assert result["status"] == "FAILED"
    assert result["error_code"] == "INVALID_TASK_SPEC"
    assert result["task"] is None
    assert len(session.calls) == 1


@pytest.mark.parametrize("response,error", [
    (Response(status=429), "LLM_HTTP_ERROR"), (Response(status=503), "LLM_HTTP_ERROR"),
    (Response(status=302), "LLM_HTTP_ERROR"), (Response(finish="length"), "LLM_INCOMPLETE_RESPONSE"),
    (requests.ReadTimeout("sensitive provider text"), "LLM_TIMEOUT"),
    (requests.ConnectionError("sensitive provider text"), "LLM_CONNECTION_ERROR"),
])
def test_one_attempt_no_retry_no_fixture_fallback(response, error):
    session = Session(response)
    result = TaskUnderstandingService(LLMTaskUnderstandingProvider(config(max_retries=10), session=session)).interpret("分析豆包")
    assert result["error_code"] == error
    assert result["audit"]["attempts"] == len(session.calls) == 1
    assert result["task"] is None
    assert "sensitive" not in json.dumps(result)


@pytest.mark.parametrize("body,error", [
    (b"not json", "LLM_INVALID_RESPONSE"),
    (b"[]", "LLM_INVALID_RESPONSE"),
    (b"x" * 64001, "LLM_RESPONSE_TOO_LARGE"),
    (b"test-only-task-key", "SENSITIVE_RESPONSE_REJECTED"),
    (b'{"choices":[]}', "LLM_INVALID_RESPONSE"),
], ids=["non-json", "array", "oversized", "secret-echo", "empty-choices"])
def test_malformed_and_sensitive_transport_responses(body, error):
    response = Response()
    response.body = body
    result = LLMTaskUnderstandingProvider(config(), session=Session(response)).interpret("分析豆包")
    assert result.error == error
    assert response.closed


@pytest.mark.parametrize("changes", [{"api_key": None}, {"endpoint": "http://example.com"},
                                    {"endpoint": "https://user:password@example.com"},
                                    {"endpoint": "https://example.com?key=hidden"},
                                    {"max_calls": 0}, {"max_output_tokens": 0}])
def test_invalid_config_never_calls_network(changes):
    session = Session(Response())
    result = LLMTaskUnderstandingProvider(config(**changes), session=session).interpret("分析豆包")
    assert result.error and result.attempts == 0 and not session.calls


def test_api_is_standalone_and_defaults_to_fixture_even_with_real_configuration():
    app = FastAPI()
    app.state.settings = SimpleNamespace(llm=config(provider="openai_compatible"))
    app.include_router(router)  # Deliberately no Persistence or TaskManager.
    with TestClient(app) as client:
        response = client.post("/api/analyst/interpret", json={"text": "比较豆包和 Kimi"})
        assert response.status_code == 200
        data = response.json()["data"]
        assert data["task"]["competitors"] == ["Kimi"]
        assert data["audit"]["provider"] == "fixture"
        assert not data["audit"]["execution_started"]
        for body in ({"text": ""}, {"text": "x" * 1001}, {"text": "豆包\u0000"},
                     {"text": "分析豆包", "execute": True}, {"text": "分析豆包", "provider": "unknown"}):
            assert client.post("/api/analyst/interpret", json=body).status_code == 422


def test_explicit_api_model_selection_uses_same_validated_path(monkeypatch):
    session = Session(Response())
    monkeypatch.setattr("competitive_intel.api.task_understanding.LLMTaskUnderstandingProvider",
                        lambda cfg: LLMTaskUnderstandingProvider(cfg, session=session))
    app = FastAPI()
    app.state.settings = SimpleNamespace(llm=config())
    app.include_router(router)
    with TestClient(app) as client:
        data = client.post("/api/analyst/interpret", json={"text": "分析豆包", "provider": "openai_compatible"}).json()["data"]
    assert data["status"] == "READY" and len(session.calls) == 1


def test_cli_has_no_database_dependency_and_requires_explicit_paid_opt_in(monkeypatch, capsys):
    def forbidden(*args, **kwargs): pytest.fail("Database must not be constructed")
    monkeypatch.setattr("competitive_intel.cli.Database", forbidden)
    assert main(["interpret", "分析豆包的核心功能和定价策略"]) == 0
    assert json.loads(capsys.readouterr().out)["task"]["dimensions"] == ["core_features", "pricing"]
    assert main(["interpret", "分析它"]) == 2
    capsys.readouterr()
    assert main(["interpret", "分析豆包", "--provider", "openai_compatible"]) == 64
    assert "--allow-paid" in capsys.readouterr().err


@pytest.mark.parametrize("text", ["帮我分析豆包及其主要竞争对手", "分析豆包的核心功能和定价策略", "分析豆包和 Kimi"])
def test_legacy_chat_never_dispatches_whole_request_as_product(text):
    assert parse_analyst_command(text)["action"] == "unsupported"


def test_shortcuts_remain_compatible():
    assert parse_analyst_command("帮我分析 Notion 这个产品。") == {"action": "analyze", "name": "Notion"}
    assert parse_analyst_command("查看豆包来源") == {"action": "sources", "name": "豆包"}
    assert parse_analyst_command("分析我的世界") == {"action": "analyze", "name": "我的世界"}


def test_model_clarification_is_preserved_not_silently_executed():
    payload = plan(status="NEEDS_CLARIFICATION", target=None,
                   clarification="你指的是哪个产品或产品版本？")
    result = TaskUnderstandingService(LLMTaskUnderstandingProvider(
        config(), session=Session(Response(payload)))).interpret("分析它")
    assert result["status"] == "NEEDS_CLARIFICATION"
    assert result["task"]["target"] is None
    assert result["task"]["clarification"] == payload["clarification"]
    assert not result["audit"]["execution_started"]


def test_usage_missing_is_unknown_and_refusal_is_not_a_plan():
    session = Session(Response(usage={"prompt_tokens": True, "total_tokens": -1}))
    result = TaskUnderstandingService(LLMTaskUnderstandingProvider(config(), session=session)).interpret("分析豆包")
    assert result["audit"]["usage"] is None
    response = Response()
    response.body = json.dumps({"choices": [{"finish_reason": "stop", "message": {"refusal": "no"}}]}).encode()
    result = LLMTaskUnderstandingProvider(config(), session=Session(response)).interpret("分析豆包")
    assert result.error == "LLM_REFUSAL_OR_TOOL_CALL"


@pytest.mark.parametrize("text,language", [
    ("分析豆包", "zh-CN"),
    ("分析豆包，输出英文报告", "en"),
    ("Analyze 豆包 and write the report in English", "en"),
    ("Analyze Atlas", "en"),
    ("Analyze Atlas and write the report in Chinese", "zh-CN"),
])
def test_report_language_default_and_explicit_override(text, language):
    target = "豆包" if "豆包" in text else "Atlas"
    provider = LLMTaskUnderstandingProvider(config(), session=Session(Response(plan(target=target))))
    result = TaskUnderstandingService(provider).interpret(text)
    assert result["task"]["output_language"] == language

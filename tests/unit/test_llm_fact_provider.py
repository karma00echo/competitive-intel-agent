"""No network or paid API: safe, deliberately invented responses."""
import json
from dataclasses import replace

import pytest
import requests

from competitive_intel.api.schemas import AnalysisRequest
from competitive_intel.config import LLMSettings
from competitive_intel.domain.fact_comparison import FactNormalizer
from competitive_intel.domain.facts import FactCategory
from competitive_intel.infrastructure.facts.base import FactExtractionRequest
from competitive_intel.infrastructure.facts.llm_provider import LLMFactExtractionProvider
from competitive_intel.services.agent_runner import AgentRunner


TEXT = "Acme Docs lets teams edit documents together."


def fact():
    return {"fact_category": "FEATURE", "fact_value": {
        "feature_name": "Docs", "normalized_feature_name": "Docs",
        "feature_description": TEXT, "feature_category": "OTHER",
        "availability": None, "related_plan": None, "status": "UNKNOWN",
    }, "evidence_text": TEXT, "confidence": 0.9}


def request():
    return FactExtractionRequest("Acme", "FEATURES", "https://acme.example/product", 12,
                                 TEXT, (FactCategory.FEATURE,), {}, 5)


def config(**kwargs):
    return replace(LLMSettings(api_key="test-only-never-real", model="test-model",
                              endpoint="https://model.example/v1/chat/completions"), **kwargs)


class Response:
    def __init__(self, payload=None, status=200, **kwargs):
        self.status_code = status
        self.data = {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(
            payload if payload is not None else {"snapshot_id": 12, "facts": [fact()]})}}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 45, "total_tokens": 168}}
        self.data.update(kwargs)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield json.dumps(self.data).encode()


class Session:
    def __init__(self, responses=None):
        self.responses = list(responses or [Response()])
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_strict_output_binding_usage_no_tools_or_secrets_in_prompt():
    session = Session()
    provider = LLMFactExtractionProvider(config(), session=session)
    result = provider.extract(request())
    assert not result.error
    assert len(result.candidate_facts) == 1
    assert result.usage["total_tokens"] == 168
    assert result.attempts == 1
    _, call = session.calls[0]
    assert call["allow_redirects"] is False
    assert call["json"]["response_format"]["json_schema"]["strict"] is True
    assert "tools" not in call["json"]
    assert config().api_key not in json.dumps(call["json"])
    assert config().api_key not in repr(config())


@pytest.mark.parametrize("mutation,error", [
    (lambda p: p.update(snapshot_id=999), "WRONG_SNAPSHOT_REFERENCE"),
    (lambda p: p.update(source_url="https://invented.example"), "INVALID_SCHEMA"),
    (lambda p: p["facts"][0].update(evidence_text="Invented quote"), "EVIDENCE_NOT_FOUND"),
    (lambda p: p["facts"][0].update(evidence_text=""), "EVIDENCE_NOT_FOUND"),
    (lambda p: p["facts"][0]["fact_value"].update(feature_description="Guaranteed secure"), "UNGROUNDED_FIELD"),
    (lambda p: p["facts"][0]["fact_value"].update(normalized_feature_name="new_identity"), "UNSUPPORTED_NORMALIZED_NAME"),
    (lambda p: p["facts"][0].update(confidence=2), "INVALID_SCHEMA"),
    (lambda p: p["facts"][0].update(confidence=True), "INVALID_SCHEMA"),
    (lambda p: p["facts"][0].update(fact_category="PRICE"), "INVALID_SCHEMA"),
    (lambda p: p["facts"].append(fact()), "DUPLICATE_FACT_IDENTITY"),
])
def test_rejects_entire_invalid_page(mutation, error):
    payload = {"snapshot_id": 12, "facts": [fact()]}
    mutation(payload)
    result = LLMFactExtractionProvider(config(), session=Session([Response(payload)])).extract(request())
    assert result.error == error
    assert not result.candidate_facts


@pytest.mark.parametrize("status,error", [(401,"LLM_AUTHENTICATION_FAILED"),(403,"LLM_FORBIDDEN"),
                                            (429,"LLM_RATE_LIMITED"),(500,"LLM_HTTP_ERROR"),(302,"LLM_HTTP_ERROR")])
def test_http_errors_never_expose_body_or_fallback(status, error):
    session = Session([Response(status=status)])
    result = LLMFactExtractionProvider(config(max_retries=0), session=session).extract(request())
    assert result.error == error
    assert result.provider == "openai_compatible"
    assert not result.candidate_facts


def test_rate_limit_retry_and_total_budget():
    session = Session([Response(status=429), Response()])
    provider = LLMFactExtractionProvider(config(max_calls=2), session=session, sleeper=lambda _: None)
    assert provider.extract(request()).attempts == 2
    assert provider.extract(request()).error == "MODEL_CALL_LIMIT"
    assert len(session.calls) == 2


@pytest.mark.parametrize("exception,error", [(requests.Timeout("secret"),"LLM_TIMEOUT"),
                                               (requests.ConnectionError("secret"),"LLM_CONNECTION_ERROR")])
def test_transport_errors_not_logged_or_retried(exception, error):
    session = Session([exception])
    result = LLMFactExtractionProvider(config(), session=session).extract(request())
    assert result.error == error and result.attempts == 1
    assert "secret" not in repr(result)


@pytest.mark.parametrize("content,error", [("", "EMPTY_CONTENT"),("x"*101,"INPUT_TOO_LONG_NO_EXTRACTION")])
def test_empty_and_truncated_input_never_calls_network(content, error):
    session = Session()
    result = LLMFactExtractionProvider(config(max_input_characters=100), session=session).extract(replace(request(), clean_content=content))
    assert result.error == error and not session.calls


def test_refusal_truncation_invalid_json_no_facts_and_unconfigured():
    for message, finish, error in [({"refusal":"no"},"stop","LLM_REFUSAL"),
                                   ({"content":"{}"},"length","LLM_INCOMPLETE_RESPONSE"),
                                   ({"content":"not json"},"stop","LLM_INVALID_RESPONSE")]:
        session = Session([Response(choices=[{"finish_reason":finish,"message":message}])])
        assert LLMFactExtractionProvider(config(),session=session).extract(request()).error == error
    empty = LLMFactExtractionProvider(config(),session=Session([Response({"snapshot_id":12,"facts":[]})])).extract(request())
    assert not empty.candidate_facts and "NO_VERIFIABLE_FACTS" in empty.warnings
    session = Session()
    assert LLMFactExtractionProvider(config(api_key=None),session=session).extract(request()).error == "LLM_CONFIGURATION_REQUIRED"
    assert not session.calls


def test_existing_comparator_detects_paraphrase_so_provider_must_not_paraphrase():
    normalizer = FactNormalizer()
    original = fact()["fact_value"]
    rewritten = {**original,"feature_description":"Collaborative editing"}
    assert normalizer.canonical_json("FEATURE",original) != normalizer.canonical_json("FEATURE",rewritten)
    # This is not fixed by weakening history comparison; grounding rejects the rewrite.
    payload = {"snapshot_id":12,"facts":[{**fact(),"fact_value":rewritten}]}
    assert LLMFactExtractionProvider(config(),session=Session([Response(payload)])).extract(request()).error == "UNGROUNDED_FIELD"


def test_modes_and_usage_redaction():
    AnalysisRequest(competitor_name="Acme",search_provider="serper",fact_provider="openai_compatible")
    with pytest.raises(ValueError):
        AnalysisRequest(competitor_name="Acme",search_provider="serper")
    with pytest.raises(ValueError):
        AnalysisRequest(competitor_name="Acme",fact_provider="openai_compatible")
    value = AgentRunner._safe_value({"total_tokens":168,"access_token":"secret","prompt_tokens":"secret"})
    assert value == {"total_tokens":168,"access_token":"[REDACTED]","prompt_tokens":"[REDACTED]"}

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
    assert call["json"]["response_format"] == {"type": "json_object"}
    assert "JSON Schema" in call["json"]["messages"][0]["content"]
    assert call["json"]["max_tokens"] == config().max_output_tokens
    assert "max_completion_tokens" not in call["json"]
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


@pytest.mark.parametrize("endpoint,expected", [
    ("https://api.deepseek.com", "https://api.deepseek.com/chat/completions"),
    ("https://api.deepseek.com/", "https://api.deepseek.com/chat/completions"),
    ("https://api.deepseek.com/chat/completions", "https://api.deepseek.com/chat/completions"),
    ("https://api.deepseek.com/chat/completions/", "https://api.deepseek.com/chat/completions"),
    ("https://model.example/v1", "https://model.example/v1/chat/completions"),
])
def test_endpoint_and_json_mode(endpoint, expected):
    session = Session()
    result = LLMFactExtractionProvider(config(endpoint=endpoint), session=session).extract(request())
    assert not result.error
    url, call = session.calls[0]
    assert url == expected
    assert call["json"]["response_format"] == {"type": "json_object"}
    assert "max_completion_tokens" not in call["json"]
    assert "json_schema" not in call["json"]["response_format"]
    assert ("thinking" in call["json"]) == ("api.deepseek.com" in endpoint)
    assert result.http_audit[0]["http_status"] == 200
    assert result.http_audit[0]["duration_ms"] >= 0


def test_safe_http_audit_and_untrusted_error_message():
    for message, expected in [("Invalid request.", "Invalid request"),
                               ("Authorization: Bearer test-only-never-real " + TEXT,
                                "Provider error message withheld (not on safe allowlist).")]:
        session = Session([Response(status=400, error={"type":"invalid_request_error",
            "code":"invalid_parameter", "message":message})])
        result = LLMFactExtractionProvider(config(), session=session).extract(request())
        audit = result.http_audit[0]
        assert audit["http_status"] == 400
        assert audit["provider_error_type"] == "invalid_request_error"
        assert audit["provider_error_code"] == "invalid_parameter"
        assert audit["safe_message"] == expected
        assert audit["endpoint_path"] == "/v1/chat/completions"
        assert config().api_key not in repr(result)
        assert TEXT not in repr(result)


def test_error_identifiers_and_oversized_error_body_are_not_logged():
    for error in [{"type":TEXT,"code":config().api_key,"message":TEXT},
                  {"message":"x" * 20_000}]:
        result = LLMFactExtractionProvider(config(), session=Session([
            Response(status=400, error=error)])).extract(request())
        assert result.error == "LLM_HTTP_ERROR"
        assert result.http_audit[0]["provider_error_type"] is None
        assert result.http_audit[0]["provider_error_code"] is None
        assert TEXT not in repr(result)
        assert config().api_key not in repr(result)


def test_field_diagnostics_collect_failures_without_accepting_any_facts():
    first = fact()
    first["fact_value"].update(feature_name="Imaginary", normalized_feature_name="Imaginary",
                               status="AVAILABLE")
    second = fact()
    second["fact_value"]["feature_description"] = "Unsupported claim"
    result = LLMFactExtractionProvider(config(), session=Session([Response(
        {"snapshot_id":12,"facts":[first,second]})])).extract(request())
    assert result.error == "UNGROUNDED_FIELD"
    assert not result.candidate_facts
    diagnostics = result.evidence_diagnostics
    assert [(d["fact_index"], d["field_name"]) for d in diagnostics] == [
        (0,"feature_name"),(0,"status"),(1,"feature_description")]
    assert diagnostics[0]["field_value"] == "Imaginary"
    assert diagnostics[0]["evidence_snippet"] == TEXT
    assert diagnostics[0]["snapshot_id"] == 12
    assert diagnostics[1]["failure_type"] == "ENUM_NOT_EXPLICITLY_SUPPORTED"
    assert diagnostics[2]["failure_type"] == "VALUE_NOT_FOUND"


@pytest.mark.parametrize("mutation,reason", [
    (lambda p:p["facts"][0].update(evidence_text=""), "MISSING_EVIDENCE"),
    (lambda p:p["facts"][0].update(evidence_text="Not in snapshot"), "EVIDENCE_NOT_IN_SNAPSHOT"),
    (lambda p:p["facts"][0]["fact_value"].update(normalized_feature_name="Changed"), "UNSUPPORTED_NORMALIZATION"),
    (lambda p:p.update(snapshot_id=99), "SNAPSHOT_MISMATCH"),
])
def test_diagnostic_failure_types(mutation, reason):
    payload = {"snapshot_id":12,"facts":[fact()]}
    mutation(payload)
    result = LLMFactExtractionProvider(config(), session=Session([Response(payload)])).extract(request())
    assert result.error and not result.candidate_facts
    assert result.evidence_diagnostics[0]["failure_type"] == reason


def test_diagnostics_bound_and_redact_untrusted_text():
    item = fact()
    item["evidence_text"] = "Bearer another-secret " + "x" * 1000
    result = LLMFactExtractionProvider(config(), session=Session([Response(
        {"snapshot_id":12,"facts":[item]})])).extract(request())
    diagnostic = result.evidence_diagnostics[0]
    assert "another-secret" not in repr(diagnostic)
    assert len(diagnostic["field_value"]) <= 161
    assert len(diagnostic["evidence_snippet"]) <= 241
    assert not result.candidate_facts


@pytest.mark.parametrize("quote,category", [
    ("Docs", "DOCUMENTS"), ("Doc", "DOCUMENTS"),
    ("Document", "DOCUMENTS"), ("Documents", "DOCUMENTS"),
    ("meeting", "MEETINGS"), ("Meetings", "MEETINGS"),
    ("Meeting Notes", "MEETINGS"), ("AI Meeting Notes", "MEETINGS"),
    ("Docs → Create block-based docs that flex from a note to a full spec.", "DOCUMENTS"),
    ("AI Meeting Notes → Capture every meeting, in one shared workspace.", "MEETINGS"),
])
def test_explicit_feature_category_aliases(quote, category):
    item = fact()
    item["fact_value"].update(feature_name=quote, normalized_feature_name=quote,
                             feature_description=quote, feature_category=category)
    item["evidence_text"] = quote
    result = LLMFactExtractionProvider(config(), session=Session([Response(
        {"snapshot_id":12,"facts":[item]})])).extract(replace(request(), clean_content=quote))
    assert not result.error
    assert len(result.candidate_facts) == 1
    assert not result.evidence_diagnostics


@pytest.mark.parametrize("quote,category", [
    ("Team chat", "DOCUMENTS"), ("Meetings", "DOCUMENTS"),
    ("documentary", "DOCUMENTS"), ("Docsify", "DOCUMENTS"),
    ("documents_archive", "DOCUMENTS"), ("Docs", "MEETINGS"),
    ("Team chat", "MEETINGS"), ("premeeting", "MEETINGS"),
    ("meetings_archive", "MEETINGS"),
])
def test_category_aliases_do_not_match_unrelated_words(quote, category):
    item = fact()
    item["fact_value"].update(feature_name=quote, normalized_feature_name=quote,
                             feature_description=quote, feature_category=category)
    item["evidence_text"] = quote
    result = LLMFactExtractionProvider(config(), session=Session([Response(
        {"snapshot_id":12,"facts":[item]})])).extract(replace(request(), clean_content=quote))
    assert result.error == "UNGROUNDED_FIELD"
    assert not result.candidate_facts
    assert result.evidence_diagnostics[0]["match_strategy"] == "explicit_category_alias_word_boundary"


def test_aliases_never_normalize_descriptive_fields():
    item = fact()
    item["fact_value"].update(feature_category="DOCUMENTS", feature_description="Documents")
    item["evidence_text"] = "Docs"
    result = LLMFactExtractionProvider(config(), session=Session([Response(
        {"snapshot_id":12,"facts":[item]})])).extract(replace(request(), clean_content="Docs"))
    # "Docs" supports the category, but cannot substitute for a quoted description.
    assert result.error == "UNGROUNDED_FIELD"
    assert not result.candidate_facts
    assert result.evidence_diagnostics[0]["field_name"] == "feature_description"

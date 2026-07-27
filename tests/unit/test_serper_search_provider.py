from __future__ import annotations

import json

import pytest
import requests

from competitive_intel.domain.search import SearchIntent, SearchRequest
from competitive_intel.infrastructure.search.factory import create_search_provider
from competitive_intel.infrastructure.search.providers.serper import (
    SerperSearchProvider,
)


class Response:
    def __init__(
        self,
        status: int = 200,
        data=None,
        *,
        headers=None,
        json_error: bool = False,
    ):
        self.status_code = status
        self._data = data if data is not None else {}
        self.headers = headers or {}
        self._json_error = json_error
        self.content = json.dumps(self._data).encode()

    def json(self):
        if self._json_error:
            raise ValueError("invalid response containing secret")
        return self._data


class Session:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def request(limit=10):
    return SearchRequest(
        "Linear official website", SearchIntent.OFFICIAL_SITE,
        "en-US", "en", limit
    )


def test_parses_sorts_and_limits_supported_serper_results() -> None:
    session = Session(
        Response(
            data={
                "organic": [
                    {"position": 2, "title": "Second", "link": "https://two.example", "snippet": "2"},
                    {"position": 1, "title": "First", "link": "https://one.example", "snippet": "1"},
                    {"position": 3, "title": "Bad", "link": "javascript:bad"},
                ],
                "knowledgeGraph": {
                    "title": "Knowledge",
                    "website": "https://knowledge.example",
                    "description": "KG",
                },
                "answerBox": {
                    "title": "Answer",
                    "link": "https://answer.example",
                    "answer": "A",
                },
            },
            headers={"X-Request-ID": "request-123"},
        )
    )
    provider = SerperSearchProvider(
        "unit-test-key", session=session, max_results=3
    )
    response = provider.search(request(limit=5))
    assert response.ok
    assert response.request_id == "request-123"
    assert [item.title for item in response.results] == [
        "First", "Second", "Knowledge"
    ]
    assert [item.rank for item in response.results] == [1, 2, 3]
    assert all(item.provider == "serper" for item in response.results)
    _, kwargs = session.calls[0]
    assert kwargs["headers"]["X-API-KEY"] == "unit-test-key"
    assert kwargs["timeout"] == (5.0, 15.0)


@pytest.mark.parametrize("status", [401, 403])
def test_authentication_errors_are_not_retried_or_leaked(status) -> None:
    key = "do-not-leak-this-key"
    session = Session(Response(status=status))
    response = SerperSearchProvider(key, session=session).search(request())
    assert response.error_code == "AUTHENTICATION_ERROR"
    assert not response.retryable
    assert len(session.calls) == 1
    assert key not in response.error_message
    assert key not in repr(response)


@pytest.mark.parametrize(
    ("status", "code"),
    [(429, "RATE_LIMITED"), (500, "PROVIDER_ERROR")],
)
def test_retryable_http_errors_have_a_finite_retry_limit(status, code) -> None:
    session = Session(Response(status=status), Response(status=status))
    response = SerperSearchProvider(
        "key", session=session, max_attempts=2
    ).search(request())
    assert response.error_code == code
    assert response.retryable
    assert len(session.calls) == 2


def test_timeout_retries_but_connection_failure_does_not() -> None:
    timeouts = Session(
        requests.exceptions.ConnectTimeout(),
        requests.exceptions.ReadTimeout(),
    )
    timeout_response = SerperSearchProvider(
        "key", session=timeouts, max_attempts=2
    ).search(request())
    assert timeout_response.error_code == "TIMEOUT"
    assert timeout_response.retryable
    assert len(timeouts.calls) == 2

    network = Session(requests.exceptions.ConnectionError("secret-free"))
    network_response = SerperSearchProvider(
        "key", session=network
    ).search(request())
    assert network_response.error_code == "NETWORK_ERROR"
    assert not network_response.retryable
    assert len(network.calls) == 1


def test_empty_invalid_json_missing_fields_and_bad_urls_are_structured() -> None:
    for response, expected in (
        (Response(data={"organic": []}), "EMPTY_RESULTS"),
        (Response(json_error=True), "INVALID_RESPONSE"),
        (Response(data={"organic": [{"title": "No URL"}]}), "EMPTY_RESULTS"),
        (
            Response(data={"organic": [{"title": "Bad", "link": "file:///x"}]}),
            "EMPTY_RESULTS",
        ),
    ):
        result = SerperSearchProvider(
            "key", session=Session(response)
        ).search(request())
        assert result.error_code == expected


def test_response_size_limit_is_enforced() -> None:
    response = Response(
        data={"organic": [{"title": "A", "link": "https://example.com"}]},
        headers={"Content-Length": "1000"},
    )
    result = SerperSearchProvider(
        "key", session=Session(response), max_response_bytes=10
    ).search(request())
    assert result.error_code == "INVALID_RESPONSE"


def test_missing_key_and_invalid_endpoint_are_configuration_errors() -> None:
    with pytest.raises(ValueError, match="SEARCH_API_KEY"):
        create_search_provider("serper", api_key=None)
    with pytest.raises(ValueError, match="HTTPS"):
        SerperSearchProvider("key", endpoint="http://example.com")

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
import requests

from competitive_intel.domain.webpage import FetchPageRequest, FetchStatus
from competitive_intel.infrastructure.http.requests_fetcher import RequestsFetcher


@dataclass
class FakeHistory:
    url: str


@dataclass
class FakeResponse:
    body: bytes
    status_code: int = 200
    url: str = "https://example.com/final"
    headers: dict[str, str] = field(
        default_factory=lambda: {"Content-Type": "text/html; charset=utf-8"}
    )
    history: list[FakeHistory] = field(default_factory=list)
    encoding: str | None = "utf-8"

    def iter_content(self, chunk_size: int):
        for offset in range(0, len(self.body), chunk_size):
            yield self.body[offset : offset + chunk_size]


class FakeSession:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def get(self, url: str, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _request(**overrides) -> FetchPageRequest:
    values = {
        "url": "https://example.com/start",
        "connect_timeout": 1.5,
        "read_timeout": 3.0,
        "user_agent": "TestAgent/1.0",
        "max_response_bytes": 1024,
    }
    values.update(overrides)
    return FetchPageRequest(**values)


def test_fetches_static_html_with_explicit_http_limits() -> None:
    response = FakeResponse(
        b"<html><head><title>Example</title></head>"
        b"<body><main><p>Useful static product content for teams.</p></main></body></html>"
    )
    session = FakeSession(response)

    result = RequestsFetcher(session).fetch(_request())

    assert result.fetch_status == FetchStatus.SUCCESS
    assert result.page_title == "Example"
    assert result.raw_html and "Useful static product content" in result.raw_html
    _, kwargs = session.calls[0]
    assert kwargs["timeout"] == (1.5, 3.0)
    assert kwargs["headers"]["User-Agent"] == "TestAgent/1.0"
    assert kwargs["stream"] is True


def test_connection_timeout_is_a_failed_fetch() -> None:
    result = RequestsFetcher(
        FakeSession(requests.exceptions.ConnectTimeout("timed out"))
    ).fetch(_request())

    assert result.fetch_status == FetchStatus.FAILED
    assert result.error_code == "TIMEOUT"
    assert result.raw_html is None


def test_non_success_http_status_is_not_success() -> None:
    result = RequestsFetcher(
        FakeSession(FakeResponse(b"server error", status_code=503))
    ).fetch(_request())

    assert result.fetch_status == FetchStatus.FAILED
    assert result.error_code == "HTTP_503"


def test_redirect_chain_and_final_url_are_returned() -> None:
    response = FakeResponse(
        b"<html><body><main><p>Redirected product page content.</p></main></body></html>",
        history=[FakeHistory("http://example.com/start")],
        url="https://www.example.com/product",
    )

    result = RequestsFetcher(FakeSession(response)).fetch(_request())

    assert result.redirect_chain == (
        "http://example.com/start",
        "https://www.example.com/product",
    )
    assert result.final_url == "https://www.example.com/product"


def test_non_html_response_is_rejected() -> None:
    response = FakeResponse(
        b"%PDF",
        headers={"Content-Type": "application/pdf"},
    )

    result = RequestsFetcher(FakeSession(response)).fetch(_request())

    assert result.fetch_status == FetchStatus.FAILED
    assert result.error_code == "UNSUPPORTED_CONTENT_TYPE"


def test_response_body_over_limit_is_rejected() -> None:
    response = FakeResponse(
        b"<html>" + b"x" * 200 + b"</html>",
        headers={"Content-Type": "text/html"},
    )

    result = RequestsFetcher(FakeSession(response)).fetch(
        _request(max_response_bytes=64)
    )

    assert result.fetch_status == FetchStatus.FAILED
    assert result.error_code == "RESPONSE_TOO_LARGE"
    assert result.raw_html is None


def test_probable_javascript_shell_is_explicitly_unsupported(
    fixture_pages,
) -> None:
    html = fixture_pages["js_shell"].encode()

    result = RequestsFetcher(FakeSession(FakeResponse(html))).fetch(_request())

    assert result.fetch_status == FetchStatus.JS_UNSUPPORTED
    assert result.error_code == "PROBABLE_JS_SHELL"
    assert result.is_probable_js_shell is True


def test_encoding_error_is_reported() -> None:
    response = FakeResponse(b"\xff\xfe\xfa", encoding="utf-8")

    result = RequestsFetcher(FakeSession(response)).fetch(_request())

    assert result.fetch_status == FetchStatus.FAILED
    assert result.error_code == "ENCODING_ERROR"

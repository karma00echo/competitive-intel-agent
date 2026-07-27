"""Bounded Serper HTTP adapter; it performs search only."""

from __future__ import annotations

from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import uuid4

import requests

from competitive_intel.domain.search import (
    SearchRequest,
    SearchResponse,
    SearchResult,
)


DEFAULT_SERPER_ENDPOINT = "https://google.serper.dev/search"
RETRYABLE_HTTP = {429, 500, 502, 503, 504}


class SerperHttpSession(Protocol):
    def post(self, url: str, **kwargs: object) -> requests.Response: ...


class SerperSearchProvider:
    def __init__(
        self,
        api_key: str | None,
        *,
        endpoint: str = DEFAULT_SERPER_ENDPOINT,
        session: SerperHttpSession | None = None,
        connect_timeout: float = 5.0,
        read_timeout: float = 15.0,
        max_results: int = 10,
        max_attempts: int = 2,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        if not api_key or not api_key.strip():
            raise ValueError(
                "SEARCH_API_KEY is required when SEARCH_PROVIDER=serper."
            )
        if max_results < 1 or max_attempts < 1 or max_response_bytes < 1:
            raise ValueError("Serper limits must be positive.")
        parsed = urlsplit(endpoint)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("SEARCH_ENDPOINT must be a valid HTTPS URL.")
        self._api_key = api_key.strip()
        self._endpoint = endpoint
        self._session = session or requests.Session()
        self._timeout = (connect_timeout, read_timeout)
        self._max_results = max_results
        self._max_attempts = max_attempts
        self._max_response_bytes = max_response_bytes

    @property
    def name(self) -> str:
        return "serper"

    def search(self, request: SearchRequest) -> SearchResponse:
        request_id = f"serper-{uuid4().hex}"
        limit = min(request.limit, self._max_results)
        payload: dict[str, Any] = {"q": request.query, "num": limit}
        if request.language:
            payload["hl"] = request.language
        if "-" in request.locale:
            payload["gl"] = request.locale.rsplit("-", 1)[-1].lower()
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._session.post(
                    self._endpoint,
                    headers={
                        "X-API-KEY": self._api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=self._timeout,
                )
            except (
                requests.exceptions.ConnectTimeout,
                requests.exceptions.ReadTimeout,
            ):
                if attempt < self._max_attempts:
                    continue
                return self._error(
                    request, "TIMEOUT", "Serper request timed out.",
                    request_id, retryable=True
                )
            except requests.exceptions.ConnectionError:
                return self._error(
                    request, "NETWORK_ERROR",
                    "Could not connect to the Serper service.", request_id
                )
            except requests.exceptions.RequestException:
                return self._error(
                    request, "PROVIDER_ERROR",
                    "Serper request failed.", request_id
                )

            request_id = (
                response.headers.get("X-Request-ID")
                or response.headers.get("x-request-id")
                or request_id
            )
            status = response.status_code
            if status in {401, 403}:
                return self._error(
                    request, "AUTHENTICATION_ERROR",
                    "Serper rejected the configured credentials.",
                    request_id,
                )
            if status in RETRYABLE_HTTP:
                if attempt < self._max_attempts:
                    continue
                code = "RATE_LIMITED" if status == 429 else "PROVIDER_ERROR"
                return self._error(
                    request, code,
                    "Serper is temporarily unavailable.",
                    request_id, retryable=True
                )
            if not 200 <= status < 300:
                return self._error(
                    request, "PROVIDER_ERROR",
                    f"Serper returned HTTP {status}.", request_id
                )
            declared = response.headers.get("Content-Length")
            if declared:
                try:
                    if int(declared) > self._max_response_bytes:
                        return self._error(
                            request, "INVALID_RESPONSE",
                            "Serper response exceeded the configured limit.",
                            request_id,
                        )
                except ValueError:
                    pass
            content = response.content
            if len(content) > self._max_response_bytes:
                return self._error(
                    request, "INVALID_RESPONSE",
                    "Serper response exceeded the configured limit.",
                    request_id,
                )
            try:
                data = response.json()
            except (ValueError, requests.exceptions.JSONDecodeError):
                return self._error(
                    request, "INVALID_RESPONSE",
                    "Serper returned invalid JSON.", request_id
                )
            if not isinstance(data, dict):
                return self._error(
                    request, "INVALID_RESPONSE",
                    "Serper returned an invalid response object.", request_id
                )
            results = self._parse_results(data, request, limit)
            if not results:
                return self._error(
                    request, "EMPTY_RESULTS",
                    "Serper returned no usable webpage results.", request_id
                )
            return SearchResponse(
                request, results, self.name,
                request_id=request_id,
            )
        raise AssertionError("Serper retry loop did not return.")

    def _parse_results(
        self, data: dict[str, Any], request: SearchRequest, limit: int
    ) -> tuple[SearchResult, ...]:
        rows: list[tuple[int, str, str, str]] = []
        organic = data.get("organic")
        if isinstance(organic, list):
            for index, item in enumerate(organic, start=1):
                if not isinstance(item, dict):
                    continue
                rank = item.get("position")
                rank = rank if isinstance(rank, int) and rank > 0 else index
                rows.append(
                    (
                        rank,
                        str(item.get("title") or "").strip(),
                        str(item.get("link") or "").strip(),
                        str(item.get("snippet") or "").strip(),
                    )
                )
        next_rank = max((item[0] for item in rows), default=0) + 1
        for key in ("knowledgeGraph", "answerBox"):
            item = data.get(key)
            if not isinstance(item, dict):
                continue
            url = item.get("website") or item.get("link") or item.get("url")
            title = item.get("title") or item.get("answer") or key
            snippet = item.get("description") or item.get("snippet") or item.get("answer")
            rows.append(
                (
                    next_rank,
                    str(title or "").strip(),
                    str(url or "").strip(),
                    str(snippet or "").strip(),
                )
            )
            next_rank += 1
        output: list[SearchResult] = []
        seen: set[str] = set()
        for _, title, url, snippet in sorted(rows, key=lambda row: row[0]):
            parsed = urlsplit(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                continue
            if url in seen:
                continue
            seen.add(url)
            output.append(
                SearchResult(
                    title or parsed.netloc,
                    url,
                    snippet,
                    len(output) + 1,
                    self.name,
                    request.query,
                )
            )
            if len(output) >= limit:
                break
        return tuple(output)

    def _error(
        self,
        request: SearchRequest,
        code: str,
        message: str,
        request_id: str,
        *,
        retryable: bool = False,
    ) -> SearchResponse:
        return SearchResponse(
            request,
            (),
            self.name,
            code,
            message,
            request_id,
            retryable,
        )

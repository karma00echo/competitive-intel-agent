"""Bounded public-page fetching implemented with requests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

import requests
from bs4 import BeautifulSoup

from competitive_intel.domain.webpage import (
    FetchPageRequest,
    FetchPageResult,
    FetchStatus,
)


HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
BLOCKED_STATUS_CODES = {401, 403, 407, 429}
JS_ROOT_IDS = {"app", "root", "__next", "__nuxt"}


class HttpSession(Protocol):
    def get(self, url: str, **kwargs: object) -> requests.Response: ...


def _now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _error_result(
    request: FetchPageRequest,
    *,
    fetched_at: datetime,
    status: FetchStatus,
    error_code: str,
    error_message: str,
    final_url: str | None = None,
    redirect_chain: tuple[str, ...] = (),
    http_status: int | None = None,
    content_type: str | None = None,
    is_probable_js_shell: bool = False,
) -> FetchPageResult:
    return FetchPageResult(
        requested_url=request.url,
        final_url=final_url,
        redirect_chain=redirect_chain,
        http_status=http_status,
        content_type=content_type,
        page_title=None,
        raw_html=None,
        fetched_at=fetched_at,
        fetch_status=status,
        error_code=error_code,
        error_message=error_message,
        is_probable_js_shell=is_probable_js_shell,
    )


def _probable_js_shell(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(["script", "style", "noscript", "svg"]):
        element.decompose()
    visible_text = " ".join(soup.stripped_strings)
    has_app_root = any(soup.find(id=root_id) is not None for root_id in JS_ROOT_IDS)
    original = html.lower()
    has_framework_marker = any(
        marker in original
        for marker in ("__next_data__", "__nuxt__", "webpack", "javascript required")
    )
    return len(visible_text) < 80 and (has_app_root or has_framework_marker)


class RequestsFetcher:
    """Fetch one page without persistence, model calls, or access-control bypass."""

    def __init__(self, session: HttpSession | None = None) -> None:
        self._session = session or requests.Session()

    def fetch(self, request: FetchPageRequest) -> FetchPageResult:
        fetched_at = _now()
        try:
            response = self._session.get(
                request.url,
                headers={"User-Agent": request.user_agent},
                timeout=(request.connect_timeout, request.read_timeout),
                allow_redirects=True,
                stream=True,
            )
        except requests.exceptions.TooManyRedirects as exc:
            return _error_result(
                request,
                fetched_at=fetched_at,
                status=FetchStatus.FAILED,
                error_code="TOO_MANY_REDIRECTS",
                error_message=str(exc),
            )
        except (requests.exceptions.ConnectTimeout, requests.exceptions.ReadTimeout) as exc:
            return _error_result(
                request,
                fetched_at=fetched_at,
                status=FetchStatus.FAILED,
                error_code="TIMEOUT",
                error_message=str(exc),
            )
        except requests.exceptions.InvalidURL as exc:
            return _error_result(
                request,
                fetched_at=fetched_at,
                status=FetchStatus.FAILED,
                error_code="INVALID_URL",
                error_message=str(exc),
            )
        except requests.exceptions.ConnectionError as exc:
            return _error_result(
                request,
                fetched_at=fetched_at,
                status=FetchStatus.FAILED,
                error_code="CONNECTION_ERROR",
                error_message=str(exc),
            )
        except requests.exceptions.RequestException as exc:
            return _error_result(
                request,
                fetched_at=fetched_at,
                status=FetchStatus.FAILED,
                error_code="REQUEST_ERROR",
                error_message=str(exc),
            )

        final_url = response.url
        redirect_chain = tuple(item.url for item in response.history) + (final_url,)
        content_type_header = response.headers.get("Content-Type", "")
        content_type = content_type_header.split(";", 1)[0].strip().lower() or None

        if response.status_code == 304:
            return _error_result(
                request,
                fetched_at=fetched_at,
                status=FetchStatus.NOT_MODIFIED,
                error_code="HTTP_NOT_MODIFIED",
                error_message="Server returned HTTP 304.",
                final_url=final_url,
                redirect_chain=redirect_chain,
                http_status=304,
                content_type=content_type,
            )
        if not 200 <= response.status_code < 300:
            status = (
                FetchStatus.BLOCKED
                if response.status_code in BLOCKED_STATUS_CODES
                else FetchStatus.FAILED
            )
            return _error_result(
                request,
                fetched_at=fetched_at,
                status=status,
                error_code=f"HTTP_{response.status_code}",
                error_message=f"Server returned HTTP {response.status_code}.",
                final_url=final_url,
                redirect_chain=redirect_chain,
                http_status=response.status_code,
                content_type=content_type,
            )
        if content_type not in HTML_CONTENT_TYPES:
            return _error_result(
                request,
                fetched_at=fetched_at,
                status=FetchStatus.FAILED,
                error_code="UNSUPPORTED_CONTENT_TYPE",
                error_message=f"Unsupported content type: {content_type or 'missing'}.",
                final_url=final_url,
                redirect_chain=redirect_chain,
                http_status=response.status_code,
                content_type=content_type,
            )

        declared_length = response.headers.get("Content-Length")
        if declared_length:
            try:
                if int(declared_length) > request.max_response_bytes:
                    return _error_result(
                        request,
                        fetched_at=fetched_at,
                        status=FetchStatus.FAILED,
                        error_code="RESPONSE_TOO_LARGE",
                        error_message="Declared response body exceeds configured limit.",
                        final_url=final_url,
                        redirect_chain=redirect_chain,
                        http_status=response.status_code,
                        content_type=content_type,
                    )
            except ValueError:
                pass

        body = bytearray()
        try:
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                body.extend(chunk)
                if len(body) > request.max_response_bytes:
                    return _error_result(
                        request,
                        fetched_at=fetched_at,
                        status=FetchStatus.FAILED,
                        error_code="RESPONSE_TOO_LARGE",
                        error_message="Response body exceeds configured limit.",
                        final_url=final_url,
                        redirect_chain=redirect_chain,
                        http_status=response.status_code,
                        content_type=content_type,
                    )
        except requests.exceptions.RequestException as exc:
            return _error_result(
                request,
                fetched_at=fetched_at,
                status=FetchStatus.FAILED,
                error_code="RESPONSE_READ_ERROR",
                error_message=str(exc),
                final_url=final_url,
                redirect_chain=redirect_chain,
                http_status=response.status_code,
                content_type=content_type,
            )

        encoding = response.encoding or "utf-8"
        try:
            raw_html = bytes(body).decode(encoding, errors="strict")
        except (LookupError, UnicodeDecodeError) as exc:
            return _error_result(
                request,
                fetched_at=fetched_at,
                status=FetchStatus.FAILED,
                error_code="ENCODING_ERROR",
                error_message=str(exc),
                final_url=final_url,
                redirect_chain=redirect_chain,
                http_status=response.status_code,
                content_type=content_type,
            )

        probable_js_shell = _probable_js_shell(raw_html)
        if probable_js_shell:
            return FetchPageResult(
                requested_url=request.url,
                final_url=final_url,
                redirect_chain=redirect_chain,
                http_status=response.status_code,
                content_type=content_type,
                page_title=None,
                raw_html=raw_html,
                fetched_at=fetched_at,
                fetch_status=FetchStatus.JS_UNSUPPORTED,
                error_code="PROBABLE_JS_SHELL",
                error_message="HTML contains too little visible content and appears JS-driven.",
                is_probable_js_shell=True,
            )

        soup = BeautifulSoup(raw_html, "html.parser")
        page_title = (
            " ".join(soup.title.stripped_strings).strip() if soup.title else None
        )
        return FetchPageResult(
            requested_url=request.url,
            final_url=final_url,
            redirect_chain=redirect_chain,
            http_status=response.status_code,
            content_type=content_type,
            page_title=page_title,
            raw_html=raw_html,
            fetched_at=fetched_at,
            fetch_status=FetchStatus.SUCCESS,
        )


def fetch_page(
    request: FetchPageRequest, *, session: HttpSession | None = None
) -> FetchPageResult:
    return RequestsFetcher(session=session).fetch(request)

"""Explicit data contracts for webpage fetching, cleaning, and snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FetchStatus(StrEnum):
    """Values intentionally match the existing MySQL snapshots enum."""

    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"
    JS_UNSUPPORTED = "JS_UNSUPPORTED"
    NOT_MODIFIED = "NOT_MODIFIED"


class CleanStatus(StrEnum):
    SUCCESS = "SUCCESS"
    EMPTY = "EMPTY"


class PageChangeStatus(StrEnum):
    BASELINE = "BASELINE"
    UNCHANGED = "UNCHANGED"
    PAGE_CHANGED = "PAGE_CHANGED"
    FETCH_FAILED = "FETCH_FAILED"
    JS_UNSUPPORTED = "JS_UNSUPPORTED"
    UNSUPPORTED_CONTENT = "UNSUPPORTED_CONTENT"


@dataclass(frozen=True, slots=True)
class FetchPageRequest:
    url: str
    connect_timeout: float = 5.0
    read_timeout: float = 20.0
    user_agent: str = (
        "UniversalCompetitiveIntelligenceAgent/0.1 "
        "(public-page research; contact: local-operator)"
    )
    max_response_bytes: int = 5 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.connect_timeout <= 0 or self.read_timeout <= 0:
            raise ValueError("timeouts must be greater than zero")
        if self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be greater than zero")
        if not self.user_agent.strip():
            raise ValueError("user_agent must not be empty")


@dataclass(frozen=True, slots=True)
class FetchPageResult:
    requested_url: str
    final_url: str | None
    redirect_chain: tuple[str, ...]
    http_status: int | None
    content_type: str | None
    page_title: str | None
    raw_html: str | None
    fetched_at: datetime
    fetch_status: FetchStatus
    error_code: str | None = None
    error_message: str | None = None
    is_probable_js_shell: bool = False


@dataclass(frozen=True, slots=True)
class CleanPageRequest:
    raw_html: str
    url: str
    cleaner_version: str = "deterministic-html-v1"


@dataclass(frozen=True, slots=True)
class CleanPageResult:
    page_title: str | None
    clean_content: str
    clean_hash: str
    content_length: int
    cleaner_version: str
    clean_status: CleanStatus


@dataclass(frozen=True, slots=True)
class SnapshotPageResult:
    source_id: int
    run_id: int
    snapshot_id: int
    page_status: PageChangeStatus
    fetch_status: FetchStatus
    requested_url: str
    final_url: str | None
    previous_successful_snapshot_id: int | None
    raw_hash: str | None
    clean_hash: str | None
    error_code: str | None = None
    error_message: str | None = None

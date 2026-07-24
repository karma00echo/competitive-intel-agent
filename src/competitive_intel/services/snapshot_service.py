"""Page snapshot orchestration through the existing Persistence boundary."""

from __future__ import annotations

from hashlib import sha256
from typing import Protocol

from competitive_intel.domain.content_cleaner import clean_page
from competitive_intel.domain.webpage import (
    CleanPageRequest,
    CleanPageResult,
    CleanStatus,
    FetchPageRequest,
    FetchPageResult,
    FetchStatus,
    PageChangeStatus,
    SnapshotPageResult,
)
from competitive_intel.persistence import Persistence


class PageFetcher(Protocol):
    def fetch(self, request: FetchPageRequest) -> FetchPageResult: ...


class PageCleaner(Protocol):
    def __call__(self, request: CleanPageRequest) -> CleanPageResult: ...


class SnapshotService:
    """Fetch, clean, compare, and persist one verified source."""

    def __init__(
        self,
        persistence: Persistence,
        fetcher: PageFetcher,
        cleaner: PageCleaner = clean_page,
        *,
        cleaner_version: str = "deterministic-html-v1",
    ) -> None:
        self._persistence = persistence
        self._fetcher = fetcher
        self._cleaner = cleaner
        self._cleaner_version = cleaner_version

    def process(
        self,
        *,
        source_id: int,
        run_id: int,
        connect_timeout: float = 5.0,
        read_timeout: float = 20.0,
        user_agent: str = (
            "UniversalCompetitiveIntelligenceAgent/0.1 "
            "(public-page research; contact: local-operator)"
        ),
        max_response_bytes: int = 5 * 1024 * 1024,
    ) -> SnapshotPageResult:
        with self._persistence.transaction() as session:
            source = self._persistence.sources.get(session, source_id)
        if source is None:
            raise ValueError(f"source {source_id} does not exist")
        if (
            source["verification_status"] != "VERIFIED"
            or not source["is_active"]
        ):
            raise ValueError("snapshot service only accepts verified active sources")

        fetched = self._fetcher.fetch(
            FetchPageRequest(
                url=source["url"],
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                user_agent=user_agent,
                max_response_bytes=max_response_bytes,
            )
        )
        if fetched.fetch_status != FetchStatus.SUCCESS:
            return self._save_fetch_failure(source_id, run_id, fetched)

        cleaned = self._cleaner(
            CleanPageRequest(
                raw_html=fetched.raw_html or "",
                url=fetched.final_url or fetched.requested_url,
                cleaner_version=self._cleaner_version,
            )
        )
        if cleaned.clean_status != CleanStatus.SUCCESS:
            failed = FetchPageResult(
                requested_url=fetched.requested_url,
                final_url=fetched.final_url,
                redirect_chain=fetched.redirect_chain,
                http_status=fetched.http_status,
                content_type=fetched.content_type,
                page_title=fetched.page_title,
                raw_html=fetched.raw_html,
                fetched_at=fetched.fetched_at,
                fetch_status=FetchStatus.FAILED,
                error_code="EMPTY_CLEAN_CONTENT",
                error_message="HTML cleaning produced no stable content.",
            )
            return self._save_fetch_failure(source_id, run_id, failed)

        raw_hash = sha256((fetched.raw_html or "").encode("utf-8")).hexdigest()
        with self._persistence.transaction() as session:
            previous = self._persistence.snapshots.get_latest_successful(
                session, source_id, before_run_id=run_id
            )
            page_status = (
                PageChangeStatus.BASELINE
                if previous is None
                else (
                    PageChangeStatus.UNCHANGED
                    if previous["clean_hash"] == cleaned.clean_hash
                    else PageChangeStatus.PAGE_CHANGED
                )
            )
            snapshot_id = self._persistence.snapshots.create(
                session,
                source_id=source_id,
                run_id=run_id,
                requested_url=fetched.requested_url,
                final_url=fetched.final_url,
                http_status=fetched.http_status,
                fetch_status=FetchStatus.SUCCESS.value,
                fetched_at=fetched.fetched_at,
                page_title=cleaned.page_title or fetched.page_title,
                raw_content=fetched.raw_html,
                clean_content=cleaned.clean_content,
                raw_hash=raw_hash,
                clean_hash=cleaned.clean_hash,
                content_type=fetched.content_type,
                cleaner_version=cleaned.cleaner_version,
            )
        return SnapshotPageResult(
            source_id=source_id,
            run_id=run_id,
            snapshot_id=snapshot_id,
            page_status=page_status,
            fetch_status=FetchStatus.SUCCESS,
            requested_url=fetched.requested_url,
            final_url=fetched.final_url,
            previous_successful_snapshot_id=previous["id"] if previous else None,
            raw_hash=raw_hash,
            clean_hash=cleaned.clean_hash,
        )

    def _save_fetch_failure(
        self, source_id: int, run_id: int, fetched: FetchPageResult
    ) -> SnapshotPageResult:
        raw_hash = (
            sha256(fetched.raw_html.encode("utf-8")).hexdigest()
            if fetched.raw_html is not None
            else None
        )
        with self._persistence.transaction() as session:
            previous = self._persistence.snapshots.get_latest_successful(
                session, source_id, before_run_id=run_id
            )
            snapshot_id = self._persistence.snapshots.create(
                session,
                source_id=source_id,
                run_id=run_id,
                requested_url=fetched.requested_url,
                final_url=fetched.final_url,
                http_status=fetched.http_status,
                fetch_status=fetched.fetch_status.value,
                fetched_at=fetched.fetched_at,
                page_title=fetched.page_title,
                raw_content=fetched.raw_html,
                raw_hash=raw_hash,
                content_type=fetched.content_type,
                error_code=fetched.error_code,
                error_message=fetched.error_message,
                cleaner_version=self._cleaner_version,
            )

        if fetched.fetch_status == FetchStatus.JS_UNSUPPORTED:
            page_status = PageChangeStatus.JS_UNSUPPORTED
        elif fetched.error_code == "UNSUPPORTED_CONTENT_TYPE":
            page_status = PageChangeStatus.UNSUPPORTED_CONTENT
        else:
            page_status = PageChangeStatus.FETCH_FAILED
        return SnapshotPageResult(
            source_id=source_id,
            run_id=run_id,
            snapshot_id=snapshot_id,
            page_status=page_status,
            fetch_status=fetched.fetch_status,
            requested_url=fetched.requested_url,
            final_url=fetched.final_url,
            previous_successful_snapshot_id=previous["id"] if previous else None,
            raw_hash=raw_hash,
            clean_hash=None,
            error_code=fetched.error_code,
            error_message=fetched.error_message,
        )

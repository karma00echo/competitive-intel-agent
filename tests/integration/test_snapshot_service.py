from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from competitive_intel.domain.webpage import (
    FetchPageResult,
    FetchStatus,
    PageChangeStatus,
)
from competitive_intel.services.snapshot_service import SnapshotService

pytestmark = pytest.mark.integration


class StubFetcher:
    def __init__(self, results: list[FetchPageResult]) -> None:
        self._results = iter(results)
        self.requests = []

    def fetch(self, request):
        self.requests.append(request)
        return next(self._results)


def _fetch_result(
    *,
    html: str | None,
    fetched_at: datetime,
    status: FetchStatus = FetchStatus.SUCCESS,
    error_code: str | None = None,
    content_type: str = "text/html",
) -> FetchPageResult:
    return FetchPageResult(
        requested_url="https://example.com/product",
        final_url="https://example.com/product",
        redirect_chain=("https://example.com/product",),
        http_status=200 if status == FetchStatus.SUCCESS else None,
        content_type=content_type,
        page_title="Example",
        raw_html=html,
        fetched_at=fetched_at,
        fetch_status=status,
        error_code=error_code,
        error_message=error_code,
        is_probable_js_shell=status == FetchStatus.JS_UNSUPPORTED,
    )


def _create_source(persistence) -> tuple[int, int]:
    now = datetime.now(UTC).replace(tzinfo=None)
    with persistence.transaction() as session:
        competitor_id = persistence.competitors.create(
            session,
            canonical_name="Example",
            normalized_name="example",
            official_domain="example.com",
        )
        source_id = persistence.sources.create(
            session,
            competitor_id=competitor_id,
            source_type="HOMEPAGE",
            url="https://example.com/product",
            normalized_url="https://example.com/product",
            domain="example.com",
            verification_status="VERIFIED",
            verification_reason="Test fixture",
            confidence=Decimal("0.9900"),
            verified_at=now,
        )
    return competitor_id, source_id


def _create_run(persistence, competitor_id: int, mode: str) -> int:
    with persistence.transaction() as session:
        return persistence.agent_runs.create(
            session,
            competitor_id=competitor_id,
            input_name="Example",
            normalized_input="example",
            run_mode=mode,
            current_state="PAGE_FETCHING",
        )


def test_baseline_unchanged_and_changed_page_states(persistence, fixture_pages) -> None:
    competitor_id, source_id = _create_source(persistence)
    started = datetime.now(UTC).replace(tzinfo=None)
    fetcher = StubFetcher(
        [
            _fetch_result(html=fixture_pages["static"], fetched_at=started),
            _fetch_result(
                html=fixture_pages["static"],
                fetched_at=started + timedelta(minutes=1),
            ),
            _fetch_result(
                html=fixture_pages["changed"],
                fetched_at=started + timedelta(minutes=2),
            ),
        ]
    )
    service = SnapshotService(persistence, fetcher)

    baseline = service.process(
        source_id=source_id,
        run_id=_create_run(persistence, competitor_id, "BASELINE"),
    )
    unchanged = service.process(
        source_id=source_id,
        run_id=_create_run(persistence, competitor_id, "TRACKING"),
    )
    changed = service.process(
        source_id=source_id,
        run_id=_create_run(persistence, competitor_id, "TRACKING"),
    )

    assert baseline.page_status == PageChangeStatus.BASELINE
    assert unchanged.page_status == PageChangeStatus.UNCHANGED
    assert unchanged.clean_hash == baseline.clean_hash
    assert changed.page_status == PageChangeStatus.PAGE_CHANGED
    assert changed.clean_hash != unchanged.clean_hash


def test_failed_snapshot_is_saved_without_replacing_latest_success(
    persistence, fixture_pages
) -> None:
    competitor_id, source_id = _create_source(persistence)
    started = datetime.now(UTC).replace(tzinfo=None)
    fetcher = StubFetcher(
        [
            _fetch_result(html=fixture_pages["static"], fetched_at=started),
            _fetch_result(
                html=None,
                fetched_at=started + timedelta(minutes=1),
                status=FetchStatus.FAILED,
                error_code="TIMEOUT",
            ),
        ]
    )
    service = SnapshotService(persistence, fetcher)

    successful = service.process(
        source_id=source_id,
        run_id=_create_run(persistence, competitor_id, "BASELINE"),
    )
    failed = service.process(
        source_id=source_id,
        run_id=_create_run(persistence, competitor_id, "TRACKING"),
    )

    assert failed.page_status == PageChangeStatus.FETCH_FAILED
    with persistence.transaction() as session:
        saved_failure = persistence.snapshots.get(session, failed.snapshot_id)
        latest_success = persistence.snapshots.get_latest_successful(
            session, source_id
        )
    assert saved_failure["fetch_status"] == "FAILED"
    assert saved_failure["error_code"] == "TIMEOUT"
    assert latest_success["id"] == successful.snapshot_id


@pytest.mark.parametrize(
    ("fetch_status", "error_code", "page_status"),
    [
        (
            FetchStatus.JS_UNSUPPORTED,
            "PROBABLE_JS_SHELL",
            PageChangeStatus.JS_UNSUPPORTED,
        ),
        (
            FetchStatus.FAILED,
            "UNSUPPORTED_CONTENT_TYPE",
            PageChangeStatus.UNSUPPORTED_CONTENT,
        ),
    ],
)
def test_explicit_unsupported_page_states_are_persisted(
    persistence, fetch_status, error_code, page_status
) -> None:
    competitor_id, source_id = _create_source(persistence)
    run_id = _create_run(persistence, competitor_id, "BASELINE")
    fetcher = StubFetcher(
        [
            _fetch_result(
                html="<html><div id='root'></div></html>"
                if fetch_status == FetchStatus.JS_UNSUPPORTED
                else None,
                fetched_at=datetime.now(UTC).replace(tzinfo=None),
                status=fetch_status,
                error_code=error_code,
                content_type=(
                    "text/html"
                    if fetch_status == FetchStatus.JS_UNSUPPORTED
                    else "application/pdf"
                ),
            )
        ]
    )

    result = SnapshotService(persistence, fetcher).process(
        source_id=source_id, run_id=run_id
    )

    assert result.page_status == page_status
    with persistence.transaction() as session:
        snapshot = persistence.snapshots.get(session, result.snapshot_id)
    assert snapshot["fetch_status"] == fetch_status.value


def test_unverified_source_is_rejected_before_fetch(persistence) -> None:
    now = datetime.now(UTC).replace(tzinfo=None)
    with persistence.transaction() as session:
        competitor_id = persistence.competitors.create(
            session,
            canonical_name="Pending",
            normalized_name="pending",
        )
        source_id = persistence.sources.create(
            session,
            competitor_id=competitor_id,
            source_type="HOMEPAGE",
            url="https://pending.example/",
            normalized_url="https://pending.example/",
            domain="pending.example",
            verification_status="PENDING_CONFIRMATION",
            confidence=Decimal("0.5000"),
        )
    run_id = _create_run(persistence, competitor_id, "BASELINE")
    fetcher = StubFetcher([])

    with pytest.raises(ValueError, match="verified active"):
        SnapshotService(persistence, fetcher).process(
            source_id=source_id, run_id=run_id
        )
    assert fetcher.requests == []

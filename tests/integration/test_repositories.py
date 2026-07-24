from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

pytestmark = pytest.mark.integration


def _create_core_records(persistence):
    now = datetime.now(UTC).replace(tzinfo=None)
    with persistence.transaction() as session:
        competitor_id = persistence.competitors.create(
            session,
            canonical_name="Notion",
            normalized_name="notion",
            aliases=["Notion", "诺션"],
            official_domain="notion.so",
        )
        run_id = persistence.agent_runs.create(
            session,
            competitor_id=competitor_id,
            input_name="Notion",
            normalized_input="notion",
            run_mode="BASELINE",
        )
        source_id = persistence.sources.create(
            session,
            competitor_id=competitor_id,
            source_type="HOMEPAGE",
            url="https://www.notion.so/",
            normalized_url="https://www.notion.so/",
            domain="notion.so",
            verification_status="VERIFIED",
            verification_reason="Brand and domain signals agree.",
            confidence=Decimal("0.9800"),
            verified_at=now,
        )
    return competitor_id, run_id, source_id, now


def test_basic_create_read_update_delete_and_audit_repositories(persistence) -> None:
    competitor_id, run_id, source_id, now = _create_core_records(persistence)

    with persistence.transaction() as session:
        stage_id = persistence.stage_events.create(
            session,
            run_id=run_id,
            stage="PAGE_FETCHING",
            attempt_no=1,
            max_attempts=2,
            details={"source_count": 1},
        )
        tool_call_id = persistence.tool_calls.create(
            session,
            run_id=run_id,
            stage_event_id=stage_id,
            call_index=1,
            tool_name="future_fetch_page",
            input_summary={"url": "https://www.notion.so/"},
        )
        persistence.tool_calls.finish(
            session,
            tool_call_id,
            status="SUCCEEDED",
            output_summary={"status": 200},
            duration_ms=12,
        )
        persistence.stage_events.finish(session, stage_id, status="SUCCEEDED")

        snapshot_id = persistence.snapshots.create(
            session,
            source_id=source_id,
            run_id=run_id,
            requested_url="https://www.notion.so/",
            final_url="https://www.notion.so/",
            http_status=200,
            fetch_status="SUCCESS",
            fetched_at=now,
            page_title="Notion",
            raw_content="<main>Connected workspace</main>",
            clean_content="Connected workspace",
            raw_hash="a" * 64,
            clean_hash="b" * 64,
            content_type="text/html",
            cleaner_version="test-v1",
        )
        fact_id = persistence.product_facts.create(
            session,
            competitor_id=competitor_id,
            run_id=run_id,
            snapshot_id=snapshot_id,
            fact_category="POSITIONING",
            fact_key="positioning.primary",
            fact_value={"text": "Connected workspace"},
            value_text="Connected workspace",
            statement_type="FACT",
            source_url="https://www.notion.so/",
            evidence_text="Connected workspace",
            confidence=Decimal("0.9500"),
            evidence_status="CONFIRMED",
            extracted_at=now,
        )
        change_id = persistence.changes.create(
            session,
            competitor_id=competitor_id,
            run_id=run_id,
            change_type="ADDED",
            fact_key="positioning.primary",
            new_fact_id=fact_id,
            new_value={"text": "Connected workspace"},
            evidence_text="Connected workspace",
            confidence=Decimal("0.9500"),
            verification_status="CONFIRMED",
        )
        report_id = persistence.reports.create(
            session,
            competitor_id=competitor_id,
            run_id=run_id,
            report_type="BASELINE",
            status="GENERATED",
            content_markdown="# Notion",
            summary={"facts": 1},
            generator_version="test-v1",
        )

    with persistence.transaction() as session:
        assert persistence.competitors.get(session, competitor_id)["canonical_name"] == (
            "Notion"
        )
        assert persistence.sources.get(session, source_id)["verification_status"] == (
            "VERIFIED"
        )
        assert len(persistence.sources.list_verified(session, competitor_id)) == 1
        assert persistence.snapshots.get(session, snapshot_id)["fetch_status"] == (
            "SUCCESS"
        )
        assert persistence.product_facts.list_for_run(session, run_id)[0]["id"] == (
            fact_id
        )
        assert persistence.changes.list_for_run(session, run_id)[0]["id"] == change_id
        assert persistence.reports.get_for_run(
            session, run_id, "BASELINE"
        )["id"] == report_id
        assert persistence.agent_runs.get(session, run_id)["tool_call_count"] == 1

        persistence.competitors.update_status(session, competitor_id, "ARCHIVED")

    with persistence.transaction() as session:
        assert persistence.competitors.get(session, competitor_id)["status"] == (
            "ARCHIVED"
        )
        persistence.competitors.delete(session, competitor_id)

    with persistence.transaction() as session:
        assert persistence.competitors.get(session, competitor_id) is None


def test_transaction_rolls_back_all_repository_writes(persistence) -> None:
    with pytest.raises(RuntimeError, match="force rollback"):
        with persistence.transaction() as session:
            persistence.competitors.create(
                session,
                canonical_name="Rollback Product",
                normalized_name="rollback-product",
            )
            raise RuntimeError("force rollback")

    with persistence.transaction() as session:
        assert (
            persistence.competitors.get_by_normalized_name(
                session, "rollback-product"
            )
            is None
        )


def test_failed_snapshot_is_not_returned_as_latest_successful(persistence) -> None:
    competitor_id, first_run_id, source_id, now = _create_core_records(persistence)

    with persistence.transaction() as session:
        successful_id = persistence.snapshots.create(
            session,
            source_id=source_id,
            run_id=first_run_id,
            requested_url="https://www.notion.so/",
            final_url="https://www.notion.so/",
            http_status=200,
            fetch_status="SUCCESS",
            fetched_at=now,
            clean_content="Known successful content",
            clean_hash="c" * 64,
        )
        failed_run_id = persistence.agent_runs.create(
            session,
            competitor_id=competitor_id,
            input_name="Notion",
            normalized_input="notion",
            run_mode="TRACKING",
            current_state="PAGE_FETCHING",
        )
        failed_id = persistence.snapshots.create(
            session,
            source_id=source_id,
            run_id=failed_run_id,
            requested_url="https://www.notion.so/",
            fetch_status="FAILED",
            fetched_at=now + timedelta(minutes=10),
            error_code="TIMEOUT",
            error_message="Request timed out",
        )

    with persistence.transaction() as session:
        latest = persistence.snapshots.get_latest_successful(session, source_id)
        failed = persistence.snapshots.get(session, failed_id)
        assert failed["fetch_status"] == "FAILED"
        assert latest["id"] == successful_id
        assert latest["fetch_status"] == "SUCCESS"


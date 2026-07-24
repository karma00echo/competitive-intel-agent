from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import Engine, inspect
from sqlalchemy.exc import DBAPIError, IntegrityError

pytestmark = pytest.mark.integration


EXPECTED_TABLES = {
    "competitors",
    "sources",
    "snapshots",
    "product_facts",
    "changes",
    "reports",
    "agent_runs",
    "stage_events",
    "tool_calls",
}


def test_schema_contains_all_phase_one_tables(mysql_engine: Engine) -> None:
    inspector = inspect(mysql_engine)
    assert EXPECTED_TABLES <= set(inspector.get_table_names())


def test_key_unique_and_foreign_key_constraints(mysql_engine: Engine) -> None:
    inspector = inspect(mysql_engine)

    competitor_unique = {
        item["name"] for item in inspector.get_unique_constraints("competitors")
    }
    source_unique = {
        item["name"] for item in inspector.get_unique_constraints("sources")
    }
    snapshot_unique = {
        item["name"] for item in inspector.get_unique_constraints("snapshots")
    }
    assert "uq_competitors_normalized_name" in competitor_unique
    assert "uq_sources_competitor_url" in source_unique
    assert "uq_snapshots_source_run" in snapshot_unique

    source_foreign_keys = {
        item["name"]: item for item in inspector.get_foreign_keys("sources")
    }
    assert source_foreign_keys["fk_sources_competitor"]["referred_table"] == (
        "competitors"
    )


def test_duplicate_competitor_name_is_rejected(persistence) -> None:
    with persistence.transaction() as session:
        persistence.competitors.create(
            session,
            canonical_name="Notion",
            normalized_name="notion",
        )

    with pytest.raises(IntegrityError):
        with persistence.transaction() as session:
            persistence.competitors.create(
                session,
                canonical_name="Notion duplicate",
                normalized_name="notion",
            )


def test_source_confidence_outside_zero_to_one_is_rejected(persistence) -> None:
    with persistence.transaction() as session:
        competitor_id = persistence.competitors.create(
            session,
            canonical_name="Notion",
            normalized_name="notion",
        )

    with pytest.raises(DBAPIError) as error:
        with persistence.transaction() as session:
            persistence.sources.create(
                session,
                competitor_id=competitor_id,
                source_type="HOMEPAGE",
                url="https://www.notion.so/",
                normalized_url="https://www.notion.so/",
                domain="notion.so",
                verification_status="VERIFIED",
                confidence=Decimal("1.1000"),
            )
    assert error.value.orig.args[0] == 3819


def test_foreign_key_rejects_unknown_competitor(persistence) -> None:
    with pytest.raises(IntegrityError):
        with persistence.transaction() as session:
            persistence.sources.create(
                session,
                competitor_id=999999,
                source_type="HOMEPAGE",
                url="https://example.com/",
                normalized_url="https://example.com/",
                domain="example.com",
                verification_status="VERIFIED",
                confidence=Decimal("0.9000"),
            )

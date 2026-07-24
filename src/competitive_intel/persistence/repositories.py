"""Repository implementations for all persisted competitive-intelligence data."""

from __future__ import annotations

import json
from hashlib import sha256
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import Database


Record = dict[str, Any]


def _json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _one(session: Session, statement: str, params: Mapping[str, Any]) -> Record | None:
    row = session.execute(text(statement), params).mappings().first()
    return dict(row) if row is not None else None


def _all(session: Session, statement: str, params: Mapping[str, Any]) -> list[Record]:
    return [dict(row) for row in session.execute(text(statement), params).mappings()]


def _insert(session: Session, statement: str, params: Mapping[str, Any]) -> int:
    result = session.execute(text(statement), params)
    return int(result.lastrowid)


class CompetitorRepository:
    def create(
        self,
        session: Session,
        *,
        canonical_name: str,
        normalized_name: str,
        aliases: list[str] | None = None,
        official_domain: str | None = None,
        status: str = "ACTIVE",
    ) -> int:
        return _insert(
            session,
            """
            INSERT INTO competitors
                (canonical_name, normalized_name, aliases, official_domain, status)
            VALUES
                (:canonical_name, :normalized_name, :aliases, :official_domain, :status)
            """,
            {
                "canonical_name": canonical_name,
                "normalized_name": normalized_name,
                "aliases": _json(aliases or []),
                "official_domain": official_domain,
                "status": status,
            },
        )

    def get(self, session: Session, competitor_id: int) -> Record | None:
        return _one(
            session,
            "SELECT * FROM competitors WHERE id = :id",
            {"id": competitor_id},
        )

    def get_by_normalized_name(
        self, session: Session, normalized_name: str
    ) -> Record | None:
        return _one(
            session,
            "SELECT * FROM competitors WHERE normalized_name = :name",
            {"name": normalized_name},
        )

    def update_status(
        self, session: Session, competitor_id: int, status: str
    ) -> None:
        session.execute(
            text("UPDATE competitors SET status = :status WHERE id = :id"),
            {"id": competitor_id, "status": status},
        )

    def delete(self, session: Session, competitor_id: int) -> None:
        session.execute(
            text("DELETE FROM competitors WHERE id = :id"), {"id": competitor_id}
        )


class SourceRepository:
    def create(
        self,
        session: Session,
        *,
        competitor_id: int,
        source_type: str,
        url: str,
        normalized_url: str,
        domain: str,
        verification_status: str,
        confidence: Decimal | float,
        verification_reason: str | None = None,
        verified_at: datetime | None = None,
        is_active: bool = True,
    ) -> int:
        return _insert(
            session,
            """
            INSERT INTO sources
                (competitor_id, source_type, url, normalized_url,
                 normalized_url_hash, domain,
                 verification_status, verification_reason, confidence,
                 is_active, verified_at)
            VALUES
                (:competitor_id, :source_type, :url, :normalized_url,
                 :normalized_url_hash, :domain,
                 :verification_status, :verification_reason, :confidence,
                 :is_active, :verified_at)
            """,
            {
                **locals(),
                "normalized_url_hash": sha256(
                    normalized_url.encode("utf-8")
                ).digest(),
            },
        )

    def get(self, session: Session, source_id: int) -> Record | None:
        return _one(
            session, "SELECT * FROM sources WHERE id = :id", {"id": source_id}
        )

    def list_verified(
        self, session: Session, competitor_id: int, source_type: str | None = None
    ) -> list[Record]:
        condition = " AND source_type = :source_type" if source_type else ""
        return _all(
            session,
            f"""
            SELECT * FROM sources
            WHERE competitor_id = :competitor_id
              AND verification_status = 'VERIFIED'
              AND is_active = TRUE
              {condition}
            ORDER BY source_type, id
            """,
            {"competitor_id": competitor_id, "source_type": source_type},
        )

    def delete(self, session: Session, source_id: int) -> None:
        session.execute(text("DELETE FROM sources WHERE id = :id"), {"id": source_id})


class AgentRunRepository:
    def create(
        self,
        session: Session,
        *,
        input_name: str,
        normalized_input: str,
        run_mode: str = "UNKNOWN",
        current_state: str = "SOURCE_DISCOVERY",
        competitor_id: int | None = None,
        max_tool_calls: int = 30,
    ) -> int:
        return _insert(
            session,
            """
            INSERT INTO agent_runs
                (competitor_id, input_name, normalized_input, run_mode,
                 current_state, status, max_tool_calls)
            VALUES
                (:competitor_id, :input_name, :normalized_input, :run_mode,
                 :current_state, 'RUNNING', :max_tool_calls)
            """,
            locals(),
        )

    def get(self, session: Session, run_id: int) -> Record | None:
        return _one(
            session, "SELECT * FROM agent_runs WHERE id = :id", {"id": run_id}
        )

    def finish(
        self,
        session: Session,
        run_id: int,
        *,
        status: str,
        current_state: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        session.execute(
            text(
                """
                UPDATE agent_runs
                SET status = :status,
                    current_state = :current_state,
                    error_code = :error_code,
                    error_message = :error_message,
                    finished_at = CURRENT_TIMESTAMP(6)
                WHERE id = :id
                """
            ),
            {
                "id": run_id,
                "status": status,
                "current_state": current_state,
                "error_code": error_code,
                "error_message": error_message,
            },
        )


class SnapshotRepository:
    def create(
        self,
        session: Session,
        *,
        source_id: int,
        run_id: int,
        requested_url: str,
        fetch_status: str,
        fetched_at: datetime,
        final_url: str | None = None,
        http_status: int | None = None,
        page_title: str | None = None,
        raw_content: str | None = None,
        clean_content: str | None = None,
        raw_hash: str | None = None,
        clean_hash: str | None = None,
        content_type: str | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        cleaner_version: str | None = None,
    ) -> int:
        return _insert(
            session,
            """
            INSERT INTO snapshots
                (source_id, run_id, requested_url, final_url, http_status,
                 fetch_status, page_title, raw_content, clean_content, raw_hash,
                 clean_hash, content_type, fetched_at, error_code, error_message,
                 cleaner_version)
            VALUES
                (:source_id, :run_id, :requested_url, :final_url, :http_status,
                 :fetch_status, :page_title, :raw_content, :clean_content, :raw_hash,
                 :clean_hash, :content_type, :fetched_at, :error_code, :error_message,
                 :cleaner_version)
            """,
            locals(),
        )

    def get(self, session: Session, snapshot_id: int) -> Record | None:
        return _one(
            session, "SELECT * FROM snapshots WHERE id = :id", {"id": snapshot_id}
        )

    def get_latest_successful(
        self, session: Session, source_id: int, before_run_id: int | None = None
    ) -> Record | None:
        before = " AND run_id <> :before_run_id" if before_run_id is not None else ""
        return _one(
            session,
            f"""
            SELECT * FROM snapshots
            WHERE source_id = :source_id
              AND fetch_status = 'SUCCESS'
              {before}
            ORDER BY fetched_at DESC, id DESC
            LIMIT 1
            """,
            {"source_id": source_id, "before_run_id": before_run_id},
        )


class ProductFactRepository:
    def create(
        self,
        session: Session,
        *,
        competitor_id: int,
        run_id: int,
        snapshot_id: int,
        fact_category: str,
        fact_key: str,
        fact_value: Any,
        statement_type: str,
        source_url: str,
        evidence_text: str,
        confidence: Decimal | float,
        extracted_at: datetime,
        evidence_status: str = "PENDING",
        value_text: str | None = None,
    ) -> int:
        return _insert(
            session,
            """
            INSERT INTO product_facts
                (competitor_id, run_id, snapshot_id, fact_category, fact_key,
                 fact_value, value_text, statement_type, source_url,
                 evidence_text, confidence, evidence_status, extracted_at)
            VALUES
                (:competitor_id, :run_id, :snapshot_id, :fact_category, :fact_key,
                 :fact_value, :value_text, :statement_type, :source_url,
                 :evidence_text, :confidence, :evidence_status, :extracted_at)
            """,
            {
                **locals(),
                "fact_value": _json(fact_value),
            },
        )

    def list_for_run(self, session: Session, run_id: int) -> list[Record]:
        return _all(
            session,
            "SELECT * FROM product_facts WHERE run_id = :run_id ORDER BY id",
            {"run_id": run_id},
        )


class ChangeRepository:
    def create(
        self,
        session: Session,
        *,
        competitor_id: int,
        run_id: int,
        change_type: str,
        fact_key: str,
        old_fact_id: int | None = None,
        new_fact_id: int | None = None,
        old_value: Any = None,
        new_value: Any = None,
        evidence_text: str | None = None,
        impact_assessment: str | None = None,
        confidence: Decimal | float | None = None,
        verification_status: str = "PENDING",
    ) -> int:
        return _insert(
            session,
            """
            INSERT INTO changes
                (competitor_id, run_id, change_type, fact_key, old_fact_id,
                 new_fact_id, old_value, new_value, evidence_text,
                 impact_assessment, confidence, verification_status)
            VALUES
                (:competitor_id, :run_id, :change_type, :fact_key, :old_fact_id,
                 :new_fact_id, :old_value, :new_value, :evidence_text,
                 :impact_assessment, :confidence, :verification_status)
            """,
            {
                **locals(),
                "old_value": _json(old_value),
                "new_value": _json(new_value),
            },
        )

    def list_for_run(self, session: Session, run_id: int) -> list[Record]:
        return _all(
            session,
            "SELECT * FROM changes WHERE run_id = :run_id ORDER BY id",
            {"run_id": run_id},
        )


class ReportRepository:
    def create(
        self,
        session: Session,
        *,
        competitor_id: int,
        run_id: int,
        report_type: str,
        status: str,
        generator_version: str,
        content_markdown: str | None = None,
        summary: Any = None,
        error_message: str | None = None,
    ) -> int:
        return _insert(
            session,
            """
            INSERT INTO reports
                (competitor_id, run_id, report_type, status, content_markdown,
                 summary_json, generator_version, error_message)
            VALUES
                (:competitor_id, :run_id, :report_type, :status, :content_markdown,
                 :summary_json, :generator_version, :error_message)
            """,
            {
                **locals(),
                "summary_json": _json(summary),
            },
        )

    def get_for_run(
        self, session: Session, run_id: int, report_type: str
    ) -> Record | None:
        return _one(
            session,
            """
            SELECT * FROM reports
            WHERE run_id = :run_id AND report_type = :report_type
            """,
            {"run_id": run_id, "report_type": report_type},
        )


class StageEventRepository:
    def create(
        self,
        session: Session,
        *,
        run_id: int,
        stage: str,
        attempt_no: int,
        max_attempts: int,
        status: str = "ENTERED",
        details: Any = None,
    ) -> int:
        return _insert(
            session,
            """
            INSERT INTO stage_events
                (run_id, stage, attempt_no, max_attempts, status, details_json)
            VALUES
                (:run_id, :stage, :attempt_no, :max_attempts, :status, :details_json)
            """,
            {
                **locals(),
                "details_json": _json(details),
            },
        )

    def finish(
        self,
        session: Session,
        event_id: int,
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        session.execute(
            text(
                """
                UPDATE stage_events
                SET status = :status, error_code = :error_code,
                    error_message = :error_message,
                    finished_at = CURRENT_TIMESTAMP(6)
                WHERE id = :id
                """
            ),
            {
                "id": event_id,
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
            },
        )


class ToolCallRepository:
    def create(
        self,
        session: Session,
        *,
        run_id: int,
        stage_event_id: int | None,
        call_index: int,
        tool_name: str,
        input_summary: Any = None,
    ) -> int:
        call_id = _insert(
            session,
            """
            INSERT INTO tool_calls
                (run_id, stage_event_id, call_index, tool_name, input_summary,
                 status)
            VALUES
                (:run_id, :stage_event_id, :call_index, :tool_name,
                 :input_summary, 'RUNNING')
            """,
            {
                **locals(),
                "input_summary": _json(input_summary),
            },
        )
        session.execute(
            text(
                """
                UPDATE agent_runs
                SET tool_call_count = tool_call_count + 1
                WHERE id = :run_id
                """
            ),
            {"run_id": run_id},
        )
        return call_id

    def finish(
        self,
        session: Session,
        call_id: int,
        *,
        status: str,
        output_summary: Any = None,
        retryable: bool = False,
        duration_ms: int | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        session.execute(
            text(
                """
                UPDATE tool_calls
                SET status = :status, output_summary = :output_summary,
                    retryable = :retryable, duration_ms = :duration_ms,
                    error_code = :error_code, error_message = :error_message,
                    finished_at = CURRENT_TIMESTAMP(6)
                WHERE id = :id
                """
            ),
            {
                "id": call_id,
                "status": status,
                "output_summary": _json(output_summary),
                "retryable": retryable,
                "duration_ms": duration_ms,
                "error_code": error_code,
                "error_message": error_message,
            },
        )


class Persistence:
    """Repository aggregate exposed to the application layer."""

    def __init__(self, database: Database) -> None:
        self.database = database
        self.competitors = CompetitorRepository()
        self.sources = SourceRepository()
        self.agent_runs = AgentRunRepository()
        self.snapshots = SnapshotRepository()
        self.product_facts = ProductFactRepository()
        self.changes = ChangeRepository()
        self.reports = ReportRepository()
        self.stage_events = StageEventRepository()
        self.tool_calls = ToolCallRepository()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.database.transaction() as session:
            yield session

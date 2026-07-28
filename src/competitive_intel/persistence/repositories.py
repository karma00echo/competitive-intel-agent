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

    def update_official_domain(
        self, session: Session, competitor_id: int, official_domain: str
    ) -> None:
        session.execute(
            text(
                "UPDATE competitors SET official_domain = :domain WHERE id = :id"
            ),
            {"id": competitor_id, "domain": official_domain},
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

    def list_for_competitor(
        self, session: Session, competitor_id: int
    ) -> list[Record]:
        return _all(
            session,
            """
            SELECT * FROM sources
            WHERE competitor_id = :competitor_id
            ORDER BY source_type, id
            """,
            {"competitor_id": competitor_id},
        )

    def find_by_normalized_url(
        self, session: Session, competitor_id: int, normalized_url: str
    ) -> Record | None:
        return _one(
            session,
            """
            SELECT * FROM sources
            WHERE competitor_id = :competitor_id
              AND normalized_url_hash = :normalized_url_hash
            LIMIT 1
            """,
            {
                "competitor_id": competitor_id,
                "normalized_url_hash": sha256(
                    normalized_url.encode("utf-8")
                ).digest(),
            },
        )

    def update_verification(
        self,
        session: Session,
        source_id: int,
        *,
        source_type: str,
        url: str,
        normalized_url: str,
        domain: str,
        verification_status: str,
        verification_reason: str,
        confidence: Decimal | float,
        verified_at: datetime | None,
        is_active: bool = True,
    ) -> None:
        session.execute(
            text(
                """
                UPDATE sources
                SET source_type = :source_type, url = :url,
                    normalized_url = :normalized_url,
                    normalized_url_hash = :normalized_url_hash,
                    domain = :domain,
                    verification_status = :verification_status,
                    verification_reason = :verification_reason,
                    confidence = :confidence, verified_at = :verified_at,
                    is_active = :is_active
                WHERE id = :id
                """
            ),
            {
                "id": source_id,
                "source_type": source_type,
                "url": url,
                "normalized_url": normalized_url,
                "normalized_url_hash": sha256(
                    normalized_url.encode("utf-8")
                ).digest(),
                "domain": domain,
                "verification_status": verification_status,
                "verification_reason": verification_reason,
                "confidence": confidence,
                "verified_at": verified_at,
                "is_active": is_active,
            },
        )

    def deactivate(self, session: Session, source_id: int) -> None:
        session.execute(
            text("UPDATE sources SET is_active = FALSE WHERE id = :id"),
            {"id": source_id},
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

    def update_context(
        self,
        session: Session,
        run_id: int,
        *,
        competitor_id: int | None = None,
        run_mode: str | None = None,
        current_state: str | None = None,
    ) -> None:
        assignments: list[str] = []
        params: dict[str, Any] = {"id": run_id}
        for column, value in (
            ("competitor_id", competitor_id),
            ("run_mode", run_mode),
            ("current_state", current_state),
        ):
            if value is not None:
                assignments.append(f"{column} = :{column}")
                params[column] = value
        if assignments:
            session.execute(
                text(
                    f"UPDATE agent_runs SET {', '.join(assignments)} "
                    "WHERE id = :id"
                ),
                params,
            )

    def get_latest_for_competitor(
        self, session: Session, competitor_id: int
    ) -> Record | None:
        return _one(
            session,
            """
            SELECT * FROM agent_runs
            WHERE competitor_id = :competitor_id
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """,
            {"competitor_id": competitor_id},
        )

    def get_previous_successful_with_facts(
        self, session: Session, competitor_id: int, before_run_id: int
    ) -> Record | None:
        """Warnings are persisted as COMPLETED and are valid comparison baselines."""
        return _one(
            session,
            """
            SELECT ar.* FROM agent_runs ar
            WHERE ar.competitor_id = :competitor_id
              AND ar.id < :before_run_id
              AND ar.status = 'COMPLETED'
              AND EXISTS (
                  SELECT 1 FROM fact_observations fo WHERE fo.run_id = ar.id
              )
            ORDER BY ar.id DESC
            LIMIT 1
            """,
            {
                "competitor_id": competitor_id,
                "before_run_id": before_run_id,
            },
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

    def get_successful_for_source_run(
        self, session: Session, source_id: int, run_id: int
    ) -> Record | None:
        return _one(
            session,
            """
            SELECT * FROM snapshots
            WHERE source_id = :source_id
              AND run_id = :run_id
              AND fetch_status = 'SUCCESS'
            ORDER BY id DESC
            LIMIT 1
            """,
            {"source_id": source_id, "run_id": run_id},
        )

    def list_for_run(self, session: Session, run_id: int) -> list[Record]:
        return _all(
            session,
            "SELECT * FROM snapshots WHERE run_id = :run_id ORDER BY id",
            {"run_id": run_id},
        )

    def count_latest_successful_for_competitor(
        self, session: Session, competitor_id: int
    ) -> int:
        row = _one(
            session,
            """
            SELECT COUNT(DISTINCT s.source_id) AS count
            FROM snapshots s
            JOIN sources src ON src.id = s.source_id
            WHERE src.competitor_id = :competitor_id
              AND src.verification_status = 'VERIFIED'
              AND src.is_active = TRUE
              AND s.fetch_status = 'SUCCESS'
            """,
            {"competitor_id": competitor_id},
        )
        return int(row["count"]) if row else 0


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
        observations = _all(
            session,
            """
            SELECT pf.* FROM fact_observations fo
            JOIN product_facts pf ON pf.id = fo.fact_id
            WHERE fo.run_id = :run_id
            ORDER BY pf.id
            """,
            {"run_id": run_id},
        )
        if observations:
            return observations
        return _all(
            session,
            "SELECT * FROM product_facts WHERE run_id = :run_id ORDER BY id",
            {"run_id": run_id},
        )

    def get(self, session: Session, fact_id: int) -> Record | None:
        return _one(
            session,
            "SELECT * FROM product_facts WHERE id = :id",
            {"id": fact_id},
        )

    def list_for_snapshot(
        self, session: Session, snapshot_id: int
    ) -> list[Record]:
        return _all(
            session,
            "SELECT * FROM product_facts WHERE snapshot_id = :snapshot_id ORDER BY id",
            {"snapshot_id": snapshot_id},
        )

    def find_by_snapshot_key(
        self, session: Session, snapshot_id: int, fact_key: str
    ) -> Record | None:
        return _one(
            session,
            """
            SELECT * FROM product_facts
            WHERE snapshot_id = :snapshot_id AND fact_key = :fact_key
            LIMIT 1
            """,
            {"snapshot_id": snapshot_id, "fact_key": fact_key},
        )

    def count_confirmed_for_competitor(
        self, session: Session, competitor_id: int
    ) -> int:
        row = _one(
            session,
            """
            SELECT COUNT(*) AS count FROM product_facts
            WHERE competitor_id = :competitor_id
              AND evidence_status = 'CONFIRMED'
              AND statement_type = 'FACT'
            """,
            {"competitor_id": competitor_id},
        )
        return int(row["count"]) if row else 0


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

    def create_idempotent(
        self,
        session: Session,
        **values: Any,
    ) -> int:
        existing = _one(
            session,
            """
            SELECT id FROM changes
            WHERE run_id = :run_id
              AND fact_key = :fact_key
              AND change_type = :change_type
            LIMIT 1
            """,
            {
                "run_id": values["run_id"],
                "fact_key": values["fact_key"],
                "change_type": values["change_type"],
            },
        )
        return int(existing["id"]) if existing else self.create(session, **values)

    def list_for_run(self, session: Session, run_id: int) -> list[Record]:
        return _all(
            session,
            "SELECT * FROM changes WHERE run_id = :run_id ORDER BY id",
            {"run_id": run_id},
        )

    def list_for_competitor(
        self, session: Session, competitor_id: int
    ) -> list[Record]:
        return _all(
            session,
            """
            SELECT * FROM changes
            WHERE competitor_id = :competitor_id
            ORDER BY created_at DESC, id DESC
            """,
            {"competitor_id": competitor_id},
        )

    def list_for_fact_key(
        self, session: Session, competitor_id: int, fact_key: str
    ) -> list[Record]:
        return _all(
            session,
            """
            SELECT * FROM changes
            WHERE competitor_id = :competitor_id AND fact_key = :fact_key
            ORDER BY created_at, id
            """,
            {"competitor_id": competitor_id, "fact_key": fact_key},
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

    def get(self, session: Session, report_id: int) -> Record | None:
        return _one(
            session,
            "SELECT * FROM reports WHERE id = :id",
            {"id": report_id},
        )

    def get_latest_for_competitor(
        self, session: Session, competitor_id: int
    ) -> Record | None:
        return _one(
            session,
            """
            SELECT * FROM reports
            WHERE competitor_id = :competitor_id AND status = 'GENERATED'
            ORDER BY generated_at DESC, id DESC
            LIMIT 1
            """,
            {"competitor_id": competitor_id},
        )


class FactVersionRepository:
    def create(
        self,
        session: Session,
        *,
        fact_id: int,
        competitor_id: int,
        source_id: int,
        normalized_value: Any,
        normalized_value_hash: str,
        valid_from: datetime,
        supersedes_fact_id: int | None = None,
        is_current: bool = False,
        comparison_status: str = "PENDING",
    ) -> None:
        session.execute(
            text(
                """
                INSERT INTO fact_versions
                    (fact_id, competitor_id, source_id, normalized_value,
                     normalized_value_hash, valid_from, supersedes_fact_id,
                     is_current, comparison_status)
                VALUES
                    (:fact_id, :competitor_id, :source_id, :normalized_value,
                     :normalized_value_hash, :valid_from, :supersedes_fact_id,
                     :is_current, :comparison_status)
                """
            ),
            {
                **locals(),
                "normalized_value": _json(normalized_value),
            },
        )

    def get(self, session: Session, fact_id: int) -> Record | None:
        return _one(
            session,
            "SELECT * FROM fact_versions WHERE fact_id = :fact_id",
            {"fact_id": fact_id},
        )

    def find_current(
        self,
        session: Session,
        competitor_id: int,
        category: str,
        fact_key: str,
    ) -> Record | None:
        return _one(
            session,
            """
            SELECT pf.*, fv.source_id, fv.normalized_value,
                   fv.normalized_value_hash, fv.valid_from, fv.valid_to,
                   fv.is_current, fv.supersedes_fact_id, fv.comparison_status
            FROM fact_versions fv
            JOIN product_facts pf ON pf.id = fv.fact_id
            WHERE fv.competitor_id = :competitor_id
              AND pf.fact_category = :category
              AND pf.fact_key = :fact_key
              AND fv.is_current = TRUE
            ORDER BY fv.valid_from DESC, fv.fact_id DESC
            LIMIT 1
            """,
            {
                "competitor_id": competitor_id,
                "category": category,
                "fact_key": fact_key,
            },
        )

    def find_latest(
        self,
        session: Session,
        competitor_id: int,
        category: str,
        fact_key: str,
    ) -> Record | None:
        return _one(
            session,
            """
            SELECT pf.*, fv.source_id, fv.normalized_value,
                   fv.normalized_value_hash, fv.valid_from, fv.valid_to,
                   fv.is_current, fv.supersedes_fact_id, fv.comparison_status
            FROM fact_versions fv
            JOIN product_facts pf ON pf.id = fv.fact_id
            WHERE fv.competitor_id = :competitor_id
              AND pf.fact_category = :category
              AND pf.fact_key = :fact_key
            ORDER BY fv.valid_from DESC, fv.fact_id DESC
            LIMIT 1
            """,
            {
                "competitor_id": competitor_id,
                "category": category,
                "fact_key": fact_key,
            },
        )

    def list_current(
        self, session: Session, competitor_id: int
    ) -> list[Record]:
        return _all(
            session,
            """
            SELECT pf.*, fv.source_id, fv.normalized_value,
                   fv.normalized_value_hash, fv.valid_from, fv.valid_to,
                   fv.is_current, fv.supersedes_fact_id, fv.comparison_status
            FROM fact_versions fv
            JOIN product_facts pf ON pf.id = fv.fact_id
            WHERE fv.competitor_id = :competitor_id
              AND fv.is_current = TRUE
            ORDER BY pf.fact_category, pf.fact_key
            """,
            {"competitor_id": competitor_id},
        )

    def activate(
        self, session: Session, fact_id: int, status: str
    ) -> None:
        session.execute(
            text(
                """
                UPDATE fact_versions
                SET is_current = TRUE, valid_to = NULL,
                    comparison_status = :status
                WHERE fact_id = :fact_id
                """
            ),
            {"fact_id": fact_id, "status": status},
        )

    def close(
        self, session: Session, fact_id: int, valid_to: datetime, status: str
    ) -> None:
        session.execute(
            text(
                """
                UPDATE fact_versions
                SET is_current = FALSE, valid_to = :valid_to,
                    comparison_status = :status
                WHERE fact_id = :fact_id
                """
            ),
            {"fact_id": fact_id, "valid_to": valid_to, "status": status},
        )

    def list_history(
        self, session: Session, competitor_id: int, fact_key: str
    ) -> list[Record]:
        return _all(
            session,
            """
            SELECT pf.*, fv.source_id, fv.normalized_value,
                   fv.valid_from, fv.valid_to, fv.is_current,
                   fv.supersedes_fact_id, fv.comparison_status
            FROM fact_versions fv
            JOIN product_facts pf ON pf.id = fv.fact_id
            WHERE fv.competitor_id = :competitor_id
              AND pf.fact_key = :fact_key
            ORDER BY fv.valid_from, fv.fact_id
            """,
            {"competitor_id": competitor_id, "fact_key": fact_key},
        )


class FactObservationRepository:
    def create_idempotent(
        self,
        session: Session,
        *,
        competitor_id: int,
        run_id: int,
        fact_id: int,
        source_id: int,
        snapshot_id: int,
        evidence_text: str,
        confidence: Decimal | float,
        observed_at: datetime,
        comparison_status: str = "PENDING",
    ) -> tuple[int, bool]:
        existing = _one(
            session,
            """
            SELECT id FROM fact_observations
            WHERE run_id = :run_id AND fact_id = :fact_id
            """,
            {"run_id": run_id, "fact_id": fact_id},
        )
        if existing:
            return int(existing["id"]), False
        observation_id = _insert(
            session,
            """
            INSERT INTO fact_observations
                (competitor_id, run_id, fact_id, source_id, snapshot_id,
                 evidence_text, confidence, observed_at, comparison_status)
            VALUES
                (:competitor_id, :run_id, :fact_id, :source_id, :snapshot_id,
                 :evidence_text, :confidence, :observed_at, :comparison_status)
            """,
            locals(),
        )
        return observation_id, True

    def list_for_run(self, session: Session, run_id: int) -> list[Record]:
        return _all(
            session,
            """
            SELECT pf.*, fo.id AS observation_id, fo.run_id AS observed_run_id,
                   fo.source_id, fo.snapshot_id AS observed_snapshot_id,
                   fo.evidence_text AS observed_evidence,
                   fo.confidence AS observed_confidence, fo.observed_at,
                   fo.comparison_status, fv.normalized_value,
                   fv.normalized_value_hash, fv.is_current,
                   src.url AS observed_source_url
            FROM fact_observations fo
            JOIN product_facts pf ON pf.id = fo.fact_id
            JOIN fact_versions fv ON fv.fact_id = fo.fact_id
            JOIN sources src ON src.id = fo.source_id
            WHERE fo.run_id = :run_id
            ORDER BY pf.fact_category, pf.fact_key
            """,
            {"run_id": run_id},
        )

    def update_status(
        self, session: Session, run_id: int, fact_id: int, status: str
    ) -> None:
        session.execute(
            text(
                """
                UPDATE fact_observations SET comparison_status = :status
                WHERE run_id = :run_id AND fact_id = :fact_id
                """
            ),
            {"run_id": run_id, "fact_id": fact_id, "status": status},
        )

    def list_history(
        self, session: Session, fact_id: int
    ) -> list[Record]:
        return _all(
            session,
            """
            SELECT * FROM fact_observations
            WHERE fact_id = :fact_id
            ORDER BY observed_at, id
            """,
            {"fact_id": fact_id},
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

    def list_for_run(self, session: Session, run_id: int) -> list[Record]:
        return _all(
            session,
            "SELECT * FROM stage_events WHERE run_id = :run_id ORDER BY id",
            {"run_id": run_id},
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

    def list_for_run(self, session: Session, run_id: int) -> list[Record]:
        return _all(
            session,
            "SELECT * FROM tool_calls WHERE run_id = :run_id ORDER BY call_index",
            {"run_id": run_id},
        )


class DashboardRepository:
    """Bounded read models for the local API and dashboard."""

    def ping(self, session: Session) -> bool:
        row = _one(session, "SELECT 1 AS ok", {})
        return bool(row and row["ok"] == 1)

    def list_competitors(
        self,
        session: Session,
        *,
        search: str | None,
        limit: int,
        offset: int,
        sort: str,
    ) -> list[Record]:
        order = {
            "updated_desc": "c.updated_at DESC, c.id DESC",
            "name_asc": "c.canonical_name ASC, c.id ASC",
            "name_desc": "c.canonical_name DESC, c.id DESC",
        }[sort]
        where = (
            "WHERE c.canonical_name LIKE :search OR c.normalized_name LIKE :search"
            if search else ""
        )
        return _all(
            session,
            f"""
            SELECT c.id, c.canonical_name, c.normalized_name, c.official_domain,
                   c.updated_at,
                   (SELECT s.url FROM sources s
                    WHERE s.competitor_id = c.id
                      AND s.source_type = 'HOMEPAGE'
                      AND s.verification_status = 'VERIFIED'
                      AND s.is_active = TRUE
                    ORDER BY s.id DESC LIMIT 1) AS official_homepage,
                   (SELECT COUNT(*) FROM sources s
                    WHERE s.competitor_id = c.id
                      AND s.verification_status = 'VERIFIED'
                      AND s.is_active = TRUE) AS verified_source_count,
                   (SELECT COUNT(*) FROM fact_versions fv
                    WHERE fv.competitor_id = c.id
                      AND fv.is_current = TRUE) AS current_fact_count,
                   (SELECT ar.id FROM agent_runs ar
                    WHERE ar.competitor_id = c.id
                    ORDER BY ar.started_at DESC, ar.id DESC LIMIT 1) AS latest_run_id,
                   (SELECT ar.current_state FROM agent_runs ar
                    WHERE ar.competitor_id = c.id
                    ORDER BY ar.started_at DESC, ar.id DESC LIMIT 1) AS latest_run_status,
                   (SELECT r.id FROM reports r
                    WHERE r.competitor_id = c.id AND r.status = 'GENERATED'
                    ORDER BY r.generated_at DESC, r.id DESC LIMIT 1) AS latest_report_id
            FROM competitors c
            {where}
            ORDER BY {order}
            LIMIT :limit OFFSET :offset
            """,
            {
                "search": f"%{search}%" if search else None,
                "limit": limit,
                "offset": offset,
            },
        )

    def competitor_overview(
        self, session: Session, competitor_id: int
    ) -> Record | None:
        return _one(
            session,
            """
            SELECT c.*,
                   (SELECT COUNT(*) FROM sources s
                    WHERE s.competitor_id = c.id) AS source_count,
                   (SELECT COUNT(*) FROM sources s
                    WHERE s.competitor_id = c.id
                      AND s.verification_status = 'VERIFIED'
                      AND s.is_active = TRUE) AS verified_source_count,
                   (SELECT COUNT(*) FROM snapshots sn
                    JOIN sources s ON s.id = sn.source_id
                    WHERE s.competitor_id = c.id) AS snapshot_count,
                   (SELECT COUNT(*) FROM snapshots sn
                    JOIN sources s ON s.id = sn.source_id
                    WHERE s.competitor_id = c.id
                      AND sn.fetch_status = 'SUCCESS') AS successful_snapshot_count,
                   (SELECT ar.id FROM agent_runs ar
                    WHERE ar.competitor_id = c.id
                    ORDER BY ar.started_at DESC, ar.id DESC LIMIT 1) AS latest_run_id,
                   (SELECT r.id FROM reports r
                    WHERE r.competitor_id = c.id AND r.status = 'GENERATED'
                    ORDER BY r.generated_at DESC, r.id DESC LIMIT 1) AS latest_report_id
            FROM competitors c WHERE c.id = :id
            """,
            {"id": competitor_id},
        )

    def list_sources(
        self, session: Session, competitor_id: int
    ) -> list[Record]:
        return _all(
            session,
            """
            SELECT s.*,
                   (SELECT sn.fetch_status FROM snapshots sn
                    WHERE sn.source_id = s.id
                    ORDER BY sn.fetched_at DESC, sn.id DESC LIMIT 1)
                       AS latest_snapshot_status,
                   (SELECT sn.fetched_at FROM snapshots sn
                    WHERE sn.source_id = s.id
                    ORDER BY sn.fetched_at DESC, sn.id DESC LIMIT 1)
                       AS latest_fetched_at
            FROM sources s
            WHERE s.competitor_id = :competitor_id
            ORDER BY s.source_type, s.id
            """,
            {"competitor_id": competitor_id},
        )

    def list_reports(
        self, session: Session, competitor_id: int
    ) -> list[Record]:
        return _all(
            session,
            """
            SELECT * FROM reports
            WHERE competitor_id = :competitor_id
            ORDER BY generated_at DESC, id DESC
            """,
            {"competitor_id": competitor_id},
        )

    def list_runs(
        self,
        session: Session,
        *,
        competitor_id: int | None,
        state: str | None,
        limit: int,
        offset: int,
    ) -> list[Record]:
        clauses: list[str] = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if competitor_id is not None:
            clauses.append("ar.competitor_id = :competitor_id")
            params["competitor_id"] = competitor_id
        if state:
            clauses.append("ar.current_state = :state")
            params["state"] = state
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        return _all(
            session,
            f"""
            SELECT ar.*, c.canonical_name AS competitor_name,
                   (SELECT r.id FROM reports r WHERE r.run_id = ar.id
                    ORDER BY r.id DESC LIMIT 1) AS report_id
            FROM agent_runs ar
            LEFT JOIN competitors c ON c.id = ar.competitor_id
            {where}
            ORDER BY ar.started_at DESC, ar.id DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        )

    def run_detail(self, session: Session, run_id: int) -> Record | None:
        return _one(
            session,
            """
            SELECT ar.*, c.canonical_name AS competitor_name,
                   (SELECT r.id FROM reports r WHERE r.run_id = ar.id
                    ORDER BY r.id DESC LIMIT 1) AS report_id,
                   (SELECT r.summary_json FROM reports r WHERE r.run_id = ar.id
                    ORDER BY r.id DESC LIMIT 1) AS report_summary
            FROM agent_runs ar
            LEFT JOIN competitors c ON c.id = ar.competitor_id
            WHERE ar.id = :id
            """,
            {"id": run_id},
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
        self.fact_versions = FactVersionRepository()
        self.fact_observations = FactObservationRepository()
        self.changes = ChangeRepository()
        self.reports = ReportRepository()
        self.stage_events = StageEventRepository()
        self.tool_calls = ToolCallRepository()
        self.dashboard = DashboardRepository()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        with self.database.transaction() as session:
            yield session

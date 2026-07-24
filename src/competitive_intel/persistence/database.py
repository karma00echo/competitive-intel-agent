"""MySQL engine and transaction management."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from competitive_intel.config import DatabaseSettings


class Database:
    """Owns the SQLAlchemy engine and application transaction boundary."""

    def __init__(
        self,
        settings: DatabaseSettings | None = None,
        *,
        engine: Engine | None = None,
    ) -> None:
        if engine is None and settings is None:
            raise ValueError("settings or engine is required")
        self.engine = engine or create_engine(
            settings.url,
            pool_pre_ping=True,
            pool_recycle=settings.pool_recycle_seconds,
            pool_size=settings.pool_size,
            max_overflow=settings.max_overflow,
            echo=settings.echo,
            connect_args={"connect_timeout": settings.connect_timeout_seconds},
        )
        self._session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
        )

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Commit on success and roll back the entire unit of work on error."""
        session = self._session_factory()
        try:
            with session.begin():
                yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()


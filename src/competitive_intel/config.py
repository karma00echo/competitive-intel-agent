"""Environment-backed application configuration."""

from __future__ import annotations

from dataclasses import dataclass, field
from os import getenv
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class DatabaseSettings:
    host: str
    port: int
    name: str
    user: str
    password: str
    charset: str = "utf8mb4"
    pool_size: int = 5
    max_overflow: int = 10
    pool_recycle_seconds: int = 1800
    connect_timeout_seconds: int = 10
    echo: bool = False

    @property
    def url(self) -> URL:
        return URL.create(
            drivername="mysql+pymysql",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.name,
            query={"charset": self.charset},
        )

    @property
    def server_url(self) -> URL:
        return URL.create(
            drivername="mysql+pymysql",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            query={"charset": self.charset},
        )


@dataclass(frozen=True, slots=True)
class SearchSettings:
    provider: str = "fixture"
    api_key: str | None = None
    endpoint: str | None = None


@dataclass(frozen=True, slots=True)
class Settings:
    database: DatabaseSettings
    search: SearchSettings = field(default_factory=SearchSettings)

    @classmethod
    def from_env(cls, env_file: str | Path | None = ".env") -> "Settings":
        if env_file is not None:
            load_dotenv(dotenv_path=env_file, override=False)
        return cls(
            database=DatabaseSettings(
                host=getenv("DB_HOST", "127.0.0.1"),
                port=int(getenv("DB_PORT", "3306")),
                name=getenv("DB_NAME", "competitive_intel"),
                user=getenv("DB_USER", "competitive_intel_app"),
                password=getenv("DB_PASSWORD", ""),
                charset=getenv("DB_CHARSET", "utf8mb4"),
                pool_size=int(getenv("DB_POOL_SIZE", "5")),
                max_overflow=int(getenv("DB_MAX_OVERFLOW", "10")),
                pool_recycle_seconds=int(
                    getenv("DB_POOL_RECYCLE_SECONDS", "1800")
                ),
                connect_timeout_seconds=int(
                    getenv("DB_CONNECT_TIMEOUT_SECONDS", "10")
                ),
                echo=_as_bool(getenv("DB_ECHO")),
            ),
            search=SearchSettings(
                provider=getenv("SEARCH_PROVIDER", "fixture"),
                api_key=getenv("SEARCH_API_KEY") or None,
                endpoint=getenv("SEARCH_ENDPOINT") or None,
            ),
        )

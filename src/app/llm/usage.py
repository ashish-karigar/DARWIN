"""Persist token usage reported by successful Groq model calls."""

from __future__ import annotations

import os
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any

from langchain_core.callbacks import BaseCallbackHandler


DEFAULT_MODEL = "openai/gpt-oss-120b"
DEFAULT_DAILY_LIMIT = 200_000
DEFAULT_DATABASE_PATH = Path("data/telemetry/groq_usage.sqlite3")


@dataclass(frozen=True, slots=True)
class GroqDailyUsage:
    provider: str
    model: str
    used_tokens: int
    input_tokens: int
    output_tokens: int
    daily_limit_tokens: int
    remaining_tokens: int
    request_count: int
    usage_day: str
    reset_at: str
    tracked_since: str | None
    scope: str = "darwin-local"

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GroqRecentUsage:
    """Successful Groq usage still inside a rolling rate-limit window."""

    model: str
    total_tokens: int
    request_count: int
    window_seconds: float
    retry_after_seconds: float


class GroqUsageStore:
    """Stores daily totals plus short-lived events used for pacing."""

    def __init__(
        self,
        database_path: str | Path = DEFAULT_DATABASE_PATH,
        *,
        daily_limit_tokens: int | None = None,
    ) -> None:
        self.database_path = Path(database_path)
        self.daily_limit_tokens = daily_limit_tokens or int(
            os.getenv(
                "DARWIN_GROQ_DAILY_TOKEN_LIMIT",
                str(DEFAULT_DAILY_LIMIT),
            )
        )
        self._lock = Lock()

    def record(
        self,
        *,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        occurred_at: datetime | None = None,
    ) -> None:
        timestamp = self._as_utc(occurred_at or datetime.now(UTC))
        usage_day = timestamp.date().isoformat()
        input_tokens = max(0, int(input_tokens))
        output_tokens = max(0, int(output_tokens))
        total_tokens = max(0, int(total_tokens))

        if total_tokens == 0:
            total_tokens = input_tokens + output_tokens
        if total_tokens == 0:
            return

        with self._lock, self._connect() as connection:
            self._create_schema(connection)
            connection.execute(
                """
                INSERT INTO groq_daily_usage (
                    usage_day,
                    model,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    request_count,
                    first_recorded_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT(usage_day, model) DO UPDATE SET
                    input_tokens = input_tokens + excluded.input_tokens,
                    output_tokens = output_tokens + excluded.output_tokens,
                    total_tokens = total_tokens + excluded.total_tokens,
                    request_count = request_count + 1,
                    updated_at = excluded.updated_at
                """,
                (
                    usage_day,
                    model,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    timestamp.isoformat(),
                    timestamp.isoformat(),
                ),
            )
            connection.execute(
                """
                INSERT INTO groq_usage_events (
                    occurred_at,
                    model,
                    input_tokens,
                    output_tokens,
                    total_tokens
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    timestamp.isoformat(),
                    model,
                    input_tokens,
                    output_tokens,
                    total_tokens,
                ),
            )
            connection.execute(
                """
                DELETE FROM groq_usage_events
                WHERE occurred_at < ?
                """,
                ((timestamp - timedelta(days=2)).isoformat(),),
            )

    def today(
        self,
        *,
        model: str = DEFAULT_MODEL,
        now: datetime | None = None,
    ) -> GroqDailyUsage:
        timestamp = self._as_utc(now or datetime.now(UTC))
        usage_day = timestamp.date().isoformat()
        reset_at = datetime.combine(
            timestamp.date() + timedelta(days=1),
            datetime.min.time(),
            tzinfo=UTC,
        )

        with self._lock, self._connect() as connection:
            self._create_schema(connection)
            row = connection.execute(
                """
                SELECT
                    input_tokens,
                    output_tokens,
                    total_tokens,
                    request_count,
                    first_recorded_at
                FROM groq_daily_usage
                WHERE usage_day = ? AND model = ?
                """,
                (usage_day, model),
            ).fetchone()

        input_tokens, output_tokens, total_tokens, requests, tracked_since = (
            row if row is not None else (0, 0, 0, 0, None)
        )
        return GroqDailyUsage(
            provider="groq",
            model=model,
            used_tokens=total_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            daily_limit_tokens=self.daily_limit_tokens,
            remaining_tokens=max(0, self.daily_limit_tokens - total_tokens),
            request_count=requests,
            usage_day=usage_day,
            reset_at=reset_at.isoformat(),
            tracked_since=tracked_since,
        )

    def recent(
        self,
        *,
        model: str = DEFAULT_MODEL,
        window_seconds: float = 60.0,
        now: datetime | None = None,
    ) -> GroqRecentUsage:
        """Returns usage that still counts against a rolling window."""

        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero")

        timestamp = self._as_utc(now or datetime.now(UTC))
        cutoff = timestamp - timedelta(seconds=window_seconds)

        with self._lock, self._connect() as connection:
            self._create_schema(connection)
            row = connection.execute(
                """
                SELECT
                    COALESCE(SUM(total_tokens), 0),
                    COUNT(*),
                    MIN(occurred_at)
                FROM groq_usage_events
                WHERE model = ? AND occurred_at > ?
                """,
                (model, cutoff.isoformat()),
            ).fetchone()

        total_tokens, request_count, oldest_value = row or (0, 0, None)
        retry_after = 0.0
        if oldest_value is not None:
            oldest = self._as_utc(datetime.fromisoformat(oldest_value))
            age_seconds = (timestamp - oldest).total_seconds()
            retry_after = max(0.0, window_seconds - age_seconds)

        return GroqRecentUsage(
            model=model,
            total_tokens=int(total_tokens),
            request_count=int(request_count),
            window_seconds=float(window_seconds),
            retry_after_seconds=round(retry_after, 3),
        )

    def _connect(self) -> sqlite3.Connection:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        return sqlite3.connect(self.database_path, timeout=5)

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS groq_daily_usage (
                usage_day TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL,
                request_count INTEGER NOT NULL,
                first_recorded_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (usage_day, model)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS groq_usage_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                occurred_at TEXT NOT NULL,
                model TEXT NOT NULL,
                input_tokens INTEGER NOT NULL,
                output_tokens INTEGER NOT NULL,
                total_tokens INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_groq_usage_events_window
            ON groq_usage_events(model, occurred_at)
            """
        )

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


class GroqUsageCallback(BaseCallbackHandler):
    """Reads authoritative token counts from LangChain Groq responses."""

    def __init__(self, store: GroqUsageStore) -> None:
        self.store = store

    def on_llm_end(self, response: Any, **kwargs: Any) -> None:
        usage, model = self._extract_usage(response)
        if usage is None:
            return

        self.store.record(
            model=model,
            input_tokens=self._integer(
                usage.get("input_tokens", usage.get("prompt_tokens", 0))
            ),
            output_tokens=self._integer(
                usage.get("output_tokens", usage.get("completion_tokens", 0))
            ),
            total_tokens=self._integer(usage.get("total_tokens", 0)),
        )

    @staticmethod
    def _extract_usage(
        response: Any,
    ) -> tuple[dict[str, Any] | None, str]:
        llm_output = getattr(response, "llm_output", None) or {}
        model = str(
            llm_output.get("model_name")
            or llm_output.get("model")
            or DEFAULT_MODEL
        )
        token_usage = llm_output.get("token_usage")

        if isinstance(token_usage, dict):
            return token_usage, model

        generations = getattr(response, "generations", ())
        for group in generations:
            for generation in group:
                message = getattr(generation, "message", None)
                usage_metadata = getattr(message, "usage_metadata", None)
                if isinstance(usage_metadata, dict):
                    response_metadata = (
                        getattr(message, "response_metadata", None) or {}
                    )
                    model = str(
                        response_metadata.get("model_name")
                        or response_metadata.get("model")
                        or model
                    )
                    return usage_metadata, model

        return None, model

    @staticmethod
    def _integer(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0


groq_usage_store = GroqUsageStore()
groq_usage_callback = GroqUsageCallback(groq_usage_store)


def get_groq_daily_usage() -> GroqDailyUsage:
    return groq_usage_store.today()

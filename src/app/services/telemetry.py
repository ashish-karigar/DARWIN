import sqlite3
from datetime import datetime, timezone
from pathlib import Path


DATABASE_PATH = Path("data/diagnostics.sqlite")


def _connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DATABASE_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS interaction_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            session_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            recording_seconds REAL,
            whisper_seconds REAL,
            reasoning_seconds REAL NOT NULL,
            first_audio_seconds REAL,
            playback_seconds REAL,
            response_characters INTEGER NOT NULL,
            success INTEGER NOT NULL,
            error_type TEXT
        )
        """
    )
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS retrieval_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            query_hash TEXT NOT NULL,
            collection_name TEXT NOT NULL,
            latency_seconds REAL NOT NULL,
            requested_k INTEGER NOT NULL,
            returned_count INTEGER NOT NULL,
            top_score REAL,
            score_threshold REAL NOT NULL
        )
        """
    )
    return connection


def record_interaction(
    *,
    session_id: str,
    mode: str,
    reasoning_seconds: float,
    response_characters: int,
    success: bool,
    recording_seconds: float | None = None,
    whisper_seconds: float | None = None,
    first_audio_seconds: float | None = None,
    playback_seconds: float | None = None,
    error_type: str | None = None,
) -> None:
    """Persist operational metrics without storing conversation content."""
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO interaction_metrics (
                created_at,
                session_id,
                mode,
                recording_seconds,
                whisper_seconds,
                reasoning_seconds,
                first_audio_seconds,
                playback_seconds,
                response_characters,
                success,
                error_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                session_id,
                mode,
                recording_seconds,
                whisper_seconds,
                reasoning_seconds,
                first_audio_seconds,
                playback_seconds,
                response_characters,
                int(success),
                error_type,
            ),
        )


def metric_count() -> int:
    with _connect() as connection:
        row = connection.execute(
            "SELECT COUNT(*) FROM interaction_metrics"
        ).fetchone()
    return int(row[0])


def record_retrieval(
    *,
    query_hash: str,
    collection_name: str,
    latency_seconds: float,
    requested_k: int,
    returned_count: int,
    top_score: float | None,
    score_threshold: float,
) -> None:
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO retrieval_metrics (
                created_at, query_hash, collection_name, latency_seconds,
                requested_k, returned_count, top_score, score_threshold
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                query_hash,
                collection_name,
                latency_seconds,
                requested_k,
                returned_count,
                top_score,
                score_threshold,
            ),
        )

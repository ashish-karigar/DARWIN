import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app.safety.models import ActionOutcome, ActionRequest


AUDIT_DATABASE_PATH = Path("data/action_audit.sqlite")


def _connect() -> sqlite3.Connection:
    AUDIT_DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(AUDIT_DATABASE_PATH)
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS action_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            action_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL,
            action_key TEXT NOT NULL,
            risk_level TEXT NOT NULL,
            summary TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            outcome TEXT NOT NULL,
            duration_seconds REAL NOT NULL,
            error_type TEXT
        )
        """
    )
    return connection


def record_action(
    request: ActionRequest,
    outcome: ActionOutcome,
    duration_seconds: float,
    error_type: str | None = None,
) -> None:
    """Record decisions and outcomes without storing credentials or tool output."""
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO action_audit (
                created_at, action_id, session_id, action_key, risk_level,
                summary, metadata_json, outcome, duration_seconds, error_type
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                request.action_id,
                request.session_id,
                request.policy.key,
                request.policy.risk.value,
                request.summary,
                json.dumps(request.metadata, sort_keys=True),
                outcome.value,
                round(duration_seconds, 6),
                error_type,
            ),
        )


def audit_health() -> tuple[bool, int]:
    with _connect() as connection:
        count = connection.execute("SELECT COUNT(*) FROM action_audit").fetchone()[0]
    return True, int(count)

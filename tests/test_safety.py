import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.safety.confirmation import set_confirmation_handler
from app.safety.confirmation import request_confirmation
from app.safety.executor import execute_guarded
from app.safety.models import ActionOutcome, ActionPolicy, ActionRequest, RiskLevel


class SafetyExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "audit.sqlite"
        self.path_patch = patch(
            "app.safety.audit.AUDIT_DATABASE_PATH",
            self.database_path,
        )
        self.path_patch.start()
        set_confirmation_handler(None)

    def tearDown(self):
        set_confirmation_handler(None)
        self.path_patch.stop()
        self.temp_directory.cleanup()

    def test_read_only_action_runs_without_confirmation(self):
        result = execute_guarded("tasks.list", "Read tasks", lambda: "done")
        self.assertEqual(result.outcome, ActionOutcome.SUCCEEDED)
        self.assertEqual(result.value, "done")

    def test_confirmation_fails_closed_without_handler(self):
        request = ActionRequest(
            action_id="test",
            policy=ActionPolicy("test.write", RiskLevel.REVERSIBLE_WRITE, "Test write"),
            summary="Test write",
            session_id="test",
        )
        self.assertFalse(request_confirmation(request))

    def test_low_impact_action_runs_without_confirmation(self):
        result = execute_guarded("music.play", "Play music", lambda: "playing")
        self.assertEqual(result.outcome, ActionOutcome.SUCCEEDED)
        self.assertEqual(result.value, "playing")

    def test_unknown_action_is_blocked(self):
        with self.assertRaises(PermissionError):
            execute_guarded("unknown.action", "Unknown", lambda: None)

    def test_audit_records_outcomes(self):
        execute_guarded("tasks.list", "Read tasks", lambda: "done")
        execute_guarded("music.play", "Play music", lambda: "playing")
        with sqlite3.connect(self.database_path) as connection:
            outcomes = [
                row[0]
                for row in connection.execute(
                    "SELECT outcome FROM action_audit ORDER BY id"
                ).fetchall()
            ]
        self.assertEqual(outcomes, ["succeeded", "succeeded"])


if __name__ == "__main__":
    unittest.main()

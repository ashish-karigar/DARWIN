"""Reuse the signed EventKit helpers used by the desktop UI."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time

from app.runtime_events import raise_if_cancelled

ROOT = Path(__file__).resolve().parents[3]


def helper_path(app: str) -> Path:
    if app not in {"Calendar", "Reminders"}:
        raise ValueError("Unsupported native helper")
    root = Path(os.environ.get("DARWIN_PROJECT_ROOT", ROOT))
    return root / "darwin-ui/native/bin" / f"DARWIN {app} Bridge.app"


def invoke_native(app: str, request: dict) -> dict:
    bundle = helper_path(app)
    if not bundle.is_dir():
        return {"ok": False, "error": "helper_unavailable"}
    raise_if_cancelled()
    with tempfile.TemporaryDirectory(prefix="darwin-agent-") as directory:
        response = Path(directory) / "response.json"
        try:
            result = subprocess.run(
                ["/usr/bin/open", "-n", str(bundle), "--args", json.dumps(request), str(response)],
                capture_output=True, timeout=10, check=False,
            )
            if result.returncode:
                return {"ok": False, "error": "helper_launch_failed"}
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                raise_if_cancelled()
                if response.exists():
                    value = json.loads(response.read_text())
                    return value if isinstance(value, dict) else {"ok": False, "error": "invalid_response"}
                time.sleep(0.1)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            return {"ok": False, "error": "helper_failed"}
    return {"ok": False, "error": "request_timed_out"}

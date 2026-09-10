import json
from pathlib import Path
from typing import Literal

from langchain_core.tools import tool
from app.safety import execute_guarded


TASKS_PATH = Path("data/tasks.txt")


def get_status(task: str) -> str:
    normalized = task.lower()

    if normalized.endswith("- done"):
        return "completed"

    if normalized.endswith("- in-progress"):
        return "in_progress"

    return "pending"


@tool
def list_tasks(
    status: Literal[
        "all",
        "incomplete",
        "completed",
        "pending",
        "in_progress",
    ] = "all",
) -> str:
    """List tasks filtered by status. Use incomplete for pending plus in-progress tasks."""

    def read_tasks() -> list[dict[str, str]]:
        return [
            {"task": line, "status": get_status(line)}
            for line in TASKS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    execution = execute_guarded(
        "tasks.list",
        "Read and filter the task list",
        read_tasks,
        metadata={"status_filter": status},
    )
    if not execution.succeeded:
        return json.dumps({"count": 0, "tasks": [], "error": "Task access failed."})
    tasks = execution.value or []

    if status == "incomplete":
        tasks = [task for task in tasks if task["status"] in {"pending", "in_progress"}]
    elif status != "all":
        tasks = [task for task in tasks if task["status"] == status]

    return json.dumps(
        {"count": len(tasks), "tasks": tasks},
        indent=2,
    )

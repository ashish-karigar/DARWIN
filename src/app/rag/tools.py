import json

from langchain_core.tools import tool

from app.rag.retriever import retrieve, search_tasks
from app.safety import execute_guarded


@tool
def knowledge_search(query: str) -> str:
    """Search for facts about DARWIN, its owner, architecture, and technology."""
    execution = execute_guarded(
        "knowledge.search",
        "Search the DARWIN knowledge base",
        lambda: retrieve(query, "darwin_knowledge"),
    )
    if not execution.succeeded:
        return json.dumps(
            {"found": False, "error": "Knowledge search was blocked or failed."}
        )
    results = execution.value or []
    return json.dumps(
        {
            "found": bool(results),
            "results": [result.to_dict() for result in results],
        }
    )


@tool
def task_search(query: str) -> str:
    """Search the user's task list,  including completed and pending tasks."""
    execution = execute_guarded(
        "tasks.list",
        "Read the task list",
        lambda: search_tasks(query),
    )
    return (
        execution.value if execution.succeeded else "Task search was blocked or failed."
    )


RAG_TOOLS = [knowledge_search, task_search]

import json

from app.ragv2.tools import knowledge_search


def run_knowledge_agent(query: str) -> str:
    """Runs verified RAG directly without a second agentic LLM hop."""

    payload = json.loads(
        knowledge_search.invoke({"query": query})
    )

    return payload["answer"]

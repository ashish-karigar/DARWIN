import json
from functools import lru_cache

from langchain_core.tools import tool

from app.ragv2.service import RagResponse, RagService
from app.runtime_events import current_runtime_request
from app.safety import execute_guarded


@lru_cache(maxsize=1)
def get_rag_service() -> RagService:
    """Keeps models and indexes warm across knowledge requests."""

    return RagService()


def serialize_response(response: RagResponse) -> str:
    """Converts the structured result into agent-safe JSON."""

    return json.dumps(
        {
            "answer": response.answer.answer,
            "grounded": response.answer.is_grounded,
            "abstained": response.answer.abstained,
            "answered_queries": response.answer.answered_queries,
            "unanswered_queries": response.answer.unanswered_queries,
            "failure_reasons": response.answer.unsupported_claims,
            "confidence_reason": response.answer.confidence_reason,
            "citations": [
                {
                    "id": citation.citation_id,
                    "document": citation.document_title,
                    "page": citation.page_number,
                    "source": citation.source_uri,
                    "heading": citation.heading_path,
                }
                for citation in response.answer.citations
            ],
            "verified": (
                response.verification.is_supported
                if response.verification is not None
                else None
            ),
            "evidence_status": response.evidence_status,
            "trace_id": response.trace_id,
            "model_calls": [
                event.as_dict()
                for event in response.model_calls
            ],
        },
        ensure_ascii=False,
    )


@tool
def knowledge_search(query: str) -> str:
    """Answer a knowledge question using verified RAG v2 evidence."""

    request_id, session_id = current_runtime_request()
    trace_arguments = {}

    if session_id != "system":
        trace_arguments["trace_thread_id"] = session_id

    if request_id != "system":
        trace_arguments["trace_request_id"] = request_id

    if trace_arguments:
        trace_arguments["trace_name"] = "knowledge-query"

    execution = execute_guarded(
        "knowledge.search",
        "Search verified DARWIN knowledge sources",
        lambda: get_rag_service().ask(
            query,
            **trace_arguments,
        ),
    )

    if not execution.succeeded or execution.value is None:
        return json.dumps(
            {
                "answer": (
                    "The verified knowledge search was blocked "
                    "or failed."
                ),
                "grounded": False,
                "abstained": True,
                "citations": [],
                "verified": False,
            }
        )

    return serialize_response(execution.value)

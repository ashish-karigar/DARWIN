from typing import TypedDict

from app.ragv2.contracts import (
    ContextBundle,
    EvidenceStatus,
    GroundedAnswer,
    VerificationResult,
)
from app.ragv2.retrieve.retrieve import RetrievalResult


class RagState(TypedDict, total=False):
    """Typed data passed between deterministic RAG graph nodes."""

    question: str
    conversation_context: tuple[str, ...]
    allow_web_search: bool

    retrieval: RetrievalResult
    correction_results: tuple[RetrievalResult, ...]
    context: ContextBundle
    evidence_status: EvidenceStatus
    remaining_queries: tuple[str, ...]
    correction_targets: tuple[str, ...]
    rewritten_queries: tuple[str, ...]

    retrieval_attempts: int
    generation_attempts: int
    web_used: bool

    answer: GroundedAnswer
    verification: VerificationResult
    route_history: tuple[str, ...]

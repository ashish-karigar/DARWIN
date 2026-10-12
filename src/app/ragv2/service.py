from collections.abc import Sequence
from dataclasses import dataclass
from itertools import count
from uuid import uuid4

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    ContextBundle,
    EvidenceStatus,
    GroundedAnswer,
    VerificationResult,
)
from app.ragv2.graph.state import RagState
from app.ragv2.graph.workflow import build_rag_graph
from app.ragv2.input_validation import (
    validate_conversation_context,
    validate_query,
)
from app.ragv2.observability.langsmith import (
    LangSmithObservability,
)
from app.ragv2.retrieve.retrieve import RetrievalResult
from app.llm.telemetry import ModelCallEvent, capture_model_calls


@dataclass(frozen=True, slots=True)
class RagResponse:
    answer: GroundedAnswer
    evidence_status: EvidenceStatus
    verification: VerificationResult | None
    retrieval_attempts: int
    web_used: bool
    route_history: tuple[str, ...]
    retrieval: RetrievalResult
    trace_id: str | None = None
    model_calls: tuple[ModelCallEvent, ...] = ()
    final_context: ContextBundle | None = None
    correction_targets: tuple[str, ...] = ()
    rewritten_queries: tuple[str, ...] = ()
    correction_results: tuple[RetrievalResult, ...] = ()


class RagService:
    """Public entry point for the complete RAG v2 workflow."""

    def __init__(
        self,
        graph=None,
        observability: LangSmithObservability | None = None,
        rag_settings: RagSettings = settings,
        trace_thread_id: str | None = None,
    ):
        self.settings = rag_settings
        self.graph = graph or build_rag_graph(
            rag_settings=rag_settings
        )
        self.observability = (
            observability or LangSmithObservability()
        )
        self.trace_thread_id = (
            trace_thread_id.strip()
            if trace_thread_id and trace_thread_id.strip()
            else f"rag-session-{uuid4()}"
        )
        self._request_numbers = count(1)

    def ask(
        self,
        question: str,
        conversation_context: Sequence[str] = (),
        *,
        allow_web_search: bool = False,
        trace_thread_id: str | None = None,
        trace_request_id: str | None = None,
        trace_name: str | None = None,
    ) -> RagResponse:
        question = validate_query(
            question,
            rag_settings=self.settings,
        )
        conversation_context = validate_conversation_context(
            conversation_context,
            rag_settings=self.settings,
        )

        request_number = next(self._request_numbers)
        thread_id = (
            trace_thread_id.strip()
            if trace_thread_id and trace_thread_id.strip()
            else self.trace_thread_id
        )
        request_id = (
            trace_request_id.strip()
            if trace_request_id and trace_request_id.strip()
            else str(uuid4())
        )
        run_name = (
            trace_name.strip()
            if trace_name and trace_name.strip()
            else f"question-{request_number:02d}"
        )

        session = self.observability.start_session(
            allow_web_search=allow_web_search,
            vector_collection=(
                self.settings.vector_collection_name
            ),
            thread_id=thread_id,
            request_id=request_id,
            run_name=run_name,
            request_number=request_number,
        )

        with self.observability.tracing_context(session):
            with capture_model_calls() as model_calls:
                final_state: RagState = self.graph.invoke(
                    {
                        "question": question,
                        "conversation_context": conversation_context,
                        "allow_web_search": allow_web_search,
                        "retrieval_attempts": 0,
                        "generation_attempts": 0,
                        "web_used": False,
                        "route_history": (),
                    },
                    config=session.runnable_config(),
                )

        answer = final_state.get("answer")

        if answer is None:
            raise RuntimeError(
                "RAG workflow completed without an answer."
            )

        return RagResponse(
            answer=answer,
            evidence_status=final_state["evidence_status"],
            verification=final_state.get("verification"),
            retrieval_attempts=final_state.get(
                "retrieval_attempts",
                0,
            ),
            web_used=final_state.get("web_used", False),
            route_history=final_state.get("route_history", ()),
            retrieval=final_state["retrieval"],
            trace_id=session.public_trace_id,
            model_calls=tuple(model_calls),
            final_context=final_state.get("context"),
            correction_targets=final_state.get(
                "correction_targets",
                (),
            ),
            rewritten_queries=final_state.get(
                "rewritten_queries",
                (),
            ),
            correction_results=final_state.get(
                "correction_results",
                (),
            ),
        )

    def ask_many(
        self,
        questions: Sequence[str],
        *,
        batch_name: str = "rag-batch",
        trace_thread_id: str | None = None,
        allow_web_search: bool = False,
    ) -> tuple[RagResponse, ...]:
        """Runs a test batch beneath one readable LangSmith trace."""

        normalized_questions = tuple(
            validate_query(question, rag_settings=self.settings)
            for question in questions
        )
        thread_id = (
            trace_thread_id.strip()
            if trace_thread_id and trace_thread_id.strip()
            else self.trace_thread_id
        )

        with self.observability.batch_context(
            batch_name=batch_name,
            thread_id=thread_id,
            questions=normalized_questions,
        ) as batch_run:
            responses = tuple(
                self.ask(
                    question,
                    allow_web_search=allow_web_search,
                    trace_thread_id=thread_id,
                    trace_name=f"question-{number:02d}",
                )
                for number, question in enumerate(
                    normalized_questions,
                    start=1,
                )
            )

            if batch_run is not None:
                batch_run.end(
                    outputs=self._batch_trace_outputs(
                        normalized_questions,
                        responses,
                    )
                )

            return responses

    @staticmethod
    def _batch_trace_outputs(
        questions: Sequence[str],
        responses: Sequence[RagResponse],
    ) -> dict:
        results = []

        for number, (question, response) in enumerate(
            zip(questions, responses, strict=True),
            start=1,
        ):
            verification = response.verification
            results.append(
                {
                    "number": number,
                    "question": question,
                    "answer": response.answer.answer,
                    "grounded": response.answer.is_grounded,
                    "abstained": response.answer.abstained,
                    "evidence_status": str(
                        response.evidence_status
                    ),
                    "verified": (
                        verification.is_supported
                        if verification is not None
                        else None
                    ),
                    "sources": [
                        {
                            "document": citation.document_title,
                            "page": citation.page_number,
                        }
                        for citation in response.answer.citations
                    ],
                    "route": list(response.route_history),
                    "failure_reasons": list(
                        response.answer.unsupported_claims
                    ),
                    "retrieval_seconds": (
                        response.retrieval.timings.total_seconds
                    ),
                    "model_calls": [
                        event.as_dict()
                        for event in response.model_calls
                    ],
                }
            )

        return {
            "summary": {
                "question_count": len(results),
                "grounded_count": sum(
                    result["grounded"] for result in results
                ),
                "abstained_count": sum(
                    result["abstained"] for result in results
                ),
                "verified_count": sum(
                    result["verified"] is True
                    for result in results
                ),
                "provider_failure_count": sum(
                    event["outcome"]
                    in {
                        "failure",
                        "rate_limited",
                        "circuit_open",
                    }
                    for result in results
                    for event in result["model_calls"]
                ),
                "fallback_used_count": sum(
                    event["outcome"] == "success"
                    and event["used_fallback"]
                    for result in results
                    for event in result["model_calls"]
                ),
                "schema_invalid_count": sum(
                    event["outcome"] == "schema_invalid"
                    for result in results
                    for event in result["model_calls"]
                ),
            },
            "results": results,
        }

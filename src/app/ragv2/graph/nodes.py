from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    ContextBundle,
    EvidenceStatus,
    GroundedAnswer,
    QueryStrategy,
)
from app.ragv2.generation.answer import GroundedAnswerGenerator
from app.ragv2.generation.verifier import AnswerVerifier
from app.ragv2.graph.state import RagState
from app.ragv2.retrieve.retrieve import RetrievalPipeline
from app.ragv2.retrieve.retrieval.context_builder import (
    ContextBuilder,
)
from app.ragv2.retrieve.retrieval.rewriter import (
    CorrectiveQueryRewriter,
)
from app.ragv2.retrieve.retrieval.web import WebEvidenceRetriever


class RagGraphNodes:
    """Small, testable operations used by the LangGraph workflow."""

    def __init__(
        self,
        retrieval_pipeline: RetrievalPipeline | None = None,
        query_rewriter: CorrectiveQueryRewriter | None = None,
        context_builder: ContextBuilder | None = None,
        web_retriever: WebEvidenceRetriever | None = None,
        answer_generator: GroundedAnswerGenerator | None = None,
        answer_verifier: AnswerVerifier | None = None,
        rag_settings: RagSettings = settings,
    ):
        self.settings = rag_settings
        self.retrieval_pipeline = (
            retrieval_pipeline
            or RetrievalPipeline(rag_settings=rag_settings)
        )
        self.query_rewriter = (
            query_rewriter or CorrectiveQueryRewriter()
        )
        self.context_builder = (
            context_builder
            or ContextBuilder(rag_settings=rag_settings)
        )
        self.web_retriever = (
            web_retriever
            or WebEvidenceRetriever(rag_settings=rag_settings)
        )
        self.answer_generator = (
            answer_generator
            or GroundedAnswerGenerator(rag_settings=rag_settings)
        )
        self.answer_verifier = (
            answer_verifier
            or AnswerVerifier(rag_settings=rag_settings)
        )

    def retrieve(self, state: RagState) -> dict:
        result = self.retrieval_pipeline.retrieve(
            state["question"],
            conversation_context=state.get(
                "conversation_context",
                (),
            ),
        )
        context = result.context
        remaining = result.unanswered_queries
        status = self._evidence_status(
            context,
            remaining,
        )

        return {
            "retrieval": result,
            "context": context,
            "remaining_queries": remaining,
            "evidence_status": status,
            "retrieval_attempts": 0,
            "generation_attempts": 0,
            "web_used": False,
            "route_history": self._route(state, "retrieve"),
        }

    def rewrite(self, state: RagState) -> dict:
        verification = state.get("verification")
        targets = state.get("remaining_queries", ())

        if verification and not verification.is_supported:
            targets = (
                *verification.unsupported_claims,
                *verification.contradicted_claims,
            )

        if not targets:
            targets = (state["question"],)

        rewritten = self.query_rewriter.rewrite(
            state["question"],
            targets,
        )

        return {
            "correction_targets": tuple(targets),
            "rewritten_queries": rewritten,
            "route_history": self._route(state, "rewrite"),
        }

    def retrieve_correction(self, state: RagState) -> dict:
        rewritten = state.get("rewritten_queries", ())
        targets = state.get("correction_targets", rewritten)
        retrieve_direct = getattr(
            self.retrieval_pipeline,
            "retrieve_direct",
            self.retrieval_pipeline.retrieve,
        )
        results = tuple(retrieve_direct(query) for query in rewritten)
        previous_context = state["context"]
        merged_context = self.context_builder.merge(
            state["question"],
            (
                previous_context,
                *(result.context for result in results),
            ),
        )
        remaining = tuple(
            target
            for target, result in zip(
                targets,
                results,
                strict=False,
            )
            if not result.fully_answerable
        )
        attempts = state.get("retrieval_attempts", 0) + 1

        return {
            "correction_results": results,
            "context": merged_context,
            "remaining_queries": remaining,
            "evidence_status": self._evidence_status(
                merged_context,
                remaining,
            ),
            "retrieval_attempts": attempts,
            "route_history": self._route(
                state,
                "retrieve_correction",
            ),
        }

    def search_web(self, state: RagState) -> dict:
        targets = (
            state.get("remaining_queries")
            or (state["question"],)
        )
        web_contexts = tuple(
            self.web_retriever.retrieve(query)
            for query in targets
        )
        merged_context = self.context_builder.merge(
            state["question"],
            (state["context"], *web_contexts),
        )
        remaining = tuple(
            target
            for target, context in zip(
                targets,
                web_contexts,
                strict=False,
            )
            if not context.has_direct_evidence
        )

        return {
            "context": merged_context,
            "remaining_queries": remaining,
            "evidence_status": self._evidence_status(
                merged_context,
                remaining,
            ),
            "web_used": True,
            "route_history": self._route(state, "search_web"),
        }

    def generate(self, state: RagState) -> dict:
        answer = self.answer_generator.generate(
            state["question"],
            state["context"],
            fully_answerable=(
                not state.get("remaining_queries", ())
                and state["context"].has_direct_evidence
            ),
            allow_partial=(
                state["evidence_status"]
                == EvidenceStatus.PARTIAL
            ),
            unanswered_queries=state.get(
                "remaining_queries",
                (),
            ),
            information_needs=self._information_needs(state),
        )

        return {
            "answer": answer,
            "generation_attempts": (
                state.get("generation_attempts", 0) + 1
            ),
            "route_history": self._route(state, "generate"),
        }

    def regenerate(self, state: RagState) -> dict:
        verification = state["verification"]
        feedback = tuple(
            dict.fromkeys(
                (
                    *verification.unsupported_claims,
                    *verification.contradicted_claims,
                )
            )
        )
        answer = self.answer_generator.generate(
            state["question"],
            state["context"],
            fully_answerable=(
                not state.get("remaining_queries", ())
                and state["context"].has_direct_evidence
            ),
            allow_partial=(
                state["evidence_status"]
                == EvidenceStatus.PARTIAL
            ),
            unanswered_queries=state.get(
                "remaining_queries",
                (),
            ),
            correction_feedback=feedback,
            information_needs=self._information_needs(state),
        )

        return {
            "answer": answer,
            "generation_attempts": (
                state.get("generation_attempts", 0) + 1
            ),
            "route_history": self._route(state, "regenerate"),
        }

    @staticmethod
    def _information_needs(state: RagState) -> tuple[str, ...]:
        """Surfaces decomposed sub-questions to the generator.

        Retrieval already splits a decompose-strategy question into
        subqueries and answers each independently, but that
        decomposition was previously discarded before generation --
        the generator only ever saw the original compound question and
        an unlabeled evidence blob, with nothing telling it the
        question had multiple parts. Only decompose has a real list of
        distinct needs; every other strategy returns () here, so this
        has no effect on direct/step_back/conversation questions.
        """

        analysis = state["retrieval"].analysis

        if analysis.strategy == QueryStrategy.DECOMPOSE:
            return analysis.subqueries

        question = state["question"].strip()

        if question.casefold().startswith("when should "):
            return (
                question,
                "What mandatory validation, completion, or exit "
                "condition does the evidence require afterward?",
            )

        return ()

    def verify(self, state: RagState) -> dict:
        verification = self.answer_verifier.verify(
            state["answer"],
            state["context"],
        )

        return {
            "verification": verification,
            "route_history": self._route(state, "verify"),
        }

    def abstain(self, state: RagState) -> dict:
        verification = state.get("verification")
        unsupported = tuple(
            dict.fromkeys(
                (
                    *state.get("remaining_queries", ()),
                    *(
                        verification.unsupported_claims
                        if verification is not None
                        else ()
                    ),
                    *(
                        verification.contradicted_claims
                        if verification is not None
                        else ()
                    ),
                )
            )
        )
        answer = GroundedAnswer(
            query=state["question"],
            answer=(
                "I don't have enough reliable evidence "
                "to answer that question."
            ),
            citations=(),
            is_grounded=False,
            abstained=True,
            unsupported_claims=unsupported,
            unanswered_queries=state.get(
                "remaining_queries",
                (),
            ),
            confidence_reason=(
                "The bounded retrieval and verification path did "
                "not find complete, supported evidence."
            ),
        )

        return {
            "answer": answer,
            "route_history": self._route(state, "abstain"),
        }

    def finalize(self, state: RagState) -> dict:
        return {
            "route_history": self._route(state, "finalize"),
        }

    def route_after_retrieval(self, state: RagState) -> str:
        status = state["evidence_status"]

        if status == EvidenceStatus.SUFFICIENT:
            return "generate"

        if (
            status == EvidenceStatus.PARTIAL
            and state.get("retrieval_attempts", 0)
            < self.settings.corrective_retrieval_limit
        ):
            return "rewrite"

        if (
            state.get("allow_web_search", False)
            and not state.get("web_used", False)
        ):
            return "search_web"

        if (
            status == EvidenceStatus.PARTIAL
            and state["context"].has_direct_evidence
        ):
            return "generate"

        return "abstain"

    @staticmethod
    def route_after_generation(state: RagState) -> str:
        return (
            "finalize"
            if state["answer"].abstained
            else "verify"
        )

    def route_after_verification(self, state: RagState) -> str:
        if state["verification"].is_supported:
            return "finalize"

        if (
            state.get("generation_attempts", 0)
            <= self.settings.verification_regeneration_limit
        ):
            return "regenerate"

        if (
            state.get("allow_web_search", False)
            and not state.get("web_used", False)
        ):
            return "search_web"

        return "abstain"

    @staticmethod
    def _evidence_status(
        context: ContextBundle,
        remaining_queries: tuple[str, ...],
    ) -> EvidenceStatus:
        if (
            context.has_direct_evidence
            and not remaining_queries
        ):
            return EvidenceStatus.SUFFICIENT

        if context.items:
            return EvidenceStatus.PARTIAL

        return EvidenceStatus.IRRELEVANT

    @staticmethod
    def _route(state: RagState, node: str) -> tuple[str, ...]:
        return (*state.get("route_history", ()), node)

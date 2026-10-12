from app.llm.models import (
    create_fallback_model,
    create_local_judge_model,
    create_local_verifier_model,
)
from app.ragv2.config import RagSettings, settings
from app.ragv2.generation.answer import (
    GroundedAnswerGenerator,
    StructuredLLMAnswerProvider,
)
from app.ragv2.generation.verifier import (
    AnswerVerifier,
    StructuredLLMVerificationProvider,
)
from app.ragv2.graph.nodes import RagGraphNodes
from app.ragv2.graph.workflow import build_rag_graph
from app.ragv2.retrieve.retrieve import RetrievalPipeline
from app.ragv2.retrieve.retrieval.context_builder import ContextBuilder
from app.ragv2.retrieve.retrieval.grader import (
    EvidenceGrader,
)
from app.ragv2.retrieve.retrieval.query_analyzer import (
    QueryAnalyzer,
    StructuredLLMQueryProvider,
)
from app.ragv2.retrieve.retrieval.rewriter import (
    CorrectiveQueryRewriter,
    StructuredLLMRewriteProvider,
)
from app.ragv2.service import RagService


def create_local_rag_service(
    rag_settings: RagSettings = settings,
) -> RagService:
    """Builds the full RAG graph with local Qwen for private evaluation."""

    answer_model = create_fallback_model()
    judge_model = create_local_judge_model()
    verifier_model = create_local_verifier_model()
    context_builder = ContextBuilder(rag_settings=rag_settings)
    retrieval = RetrievalPipeline(
        query_analyzer=QueryAnalyzer(
            provider=StructuredLLMQueryProvider(model=judge_model),
            rag_settings=rag_settings,
        ),
        evidence_grader=EvidenceGrader(
            rag_settings=rag_settings,
        ),
        context_builder=context_builder,
        rag_settings=rag_settings,
    )
    nodes = RagGraphNodes(
        retrieval_pipeline=retrieval,
        query_rewriter=CorrectiveQueryRewriter(
            provider=StructuredLLMRewriteProvider(model=judge_model)
        ),
        context_builder=context_builder,
        answer_generator=GroundedAnswerGenerator(
            provider=StructuredLLMAnswerProvider(
                model=answer_model,
                local_only=True,
            ),
            rag_settings=rag_settings,
        ),
        answer_verifier=AnswerVerifier(
            provider=StructuredLLMVerificationProvider(
                model=verifier_model,
                primary_provider="ollama",
                fallback_provider="",
            ),
            rag_settings=rag_settings,
        ),
        rag_settings=rag_settings,
    )

    return RagService(
        graph=build_rag_graph(
            nodes=nodes,
            rag_settings=rag_settings,
        ),
        rag_settings=rag_settings,
    )

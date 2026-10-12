from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    Citation,
    ContentType,
    ContextBundle,
    ContextItem,
    GroundedAnswer,
    QueryAnalysis,
    QueryStrategy,
    VerificationResult,
)
from app.ragv2.graph.nodes import RagGraphNodes
from app.ragv2.graph.workflow import build_rag_graph
from app.ragv2.retrieve.retrieve import (
    RetrievalResult,
    RetrievalTimings,
)
from app.ragv2.retrieve.retrieval.context_builder import (
    ContextBuilder,
)


class WordCounter:
    def count(self, text):
        return len(text.split())

    def truncate(self, text, maximum_tokens):
        return " ".join(text.split()[:maximum_tokens])


def make_context(*, direct=True, empty=False):
    items = ()

    if not empty:
        items = (
            ContextItem(
                parent_id=(
                    "direct-parent" if direct else "related-parent"
                ),
                document_id="document-1",
                document_title="Test document",
                text=(
                    "The direct answer is forty-two."
                    if direct
                    else "This is related background."
                ),
                content_type=ContentType.TEXT,
                source_uri="/test.txt",
                supporting_chunk_ids=("chunk-1",),
                relevance_score=0.95,
                directly_answers=direct,
                expanded_from_parent=True,
            ),
        )

    return ContextBundle(
        query="What is the answer?",
        items=items,
        total_tokens=sum(len(item.text.split()) for item in items),
        has_direct_evidence=direct and bool(items),
    )


def make_retrieval(*, answerable=True, empty=False, subqueries=()):
    context = make_context(
        direct=answerable,
        empty=empty,
    )

    return RetrievalResult(
        query="What is the answer?",
        analysis=QueryAnalysis(
            original_query="What is the answer?",
            standalone_query="What is the answer?",
            strategy=(
                QueryStrategy.DECOMPOSE
                if subqueries
                else QueryStrategy.DIRECT
            ),
            subqueries=tuple(subqueries),
        ),
        traces=(),
        candidates=(),
        reranked_hits=(),
        grades=(),
        context=context,
        unanswered_queries=(
            () if answerable else ("What is the answer?",)
        ),
        timings=RetrievalTimings(
            query_analysis_seconds=0,
            hybrid_seconds=0,
            reranking_seconds=0,
            grading_seconds=0,
            context_seconds=0,
            total_seconds=0,
        ),
    )


class SequencedRetrievalPipeline:
    def __init__(self, results):
        self.results = iter(results)
        self.calls = []

    def retrieve(self, query, conversation_context=()):
        self.calls.append(query)
        return next(self.results)


class FakeRewriter:
    def __init__(self):
        self.calls = []

    def rewrite(self, original_question, target_queries):
        self.calls.append(tuple(target_queries))
        return tuple(
            f"Rewritten: {query}"
            for query in target_queries
        )


class FakeGenerator:
    def __init__(self):
        self.calls = []
        self.information_needs_calls = []

    def generate(
        self,
        query,
        context,
        fully_answerable,
        **kwargs,
    ):
        self.calls.append(fully_answerable)
        self.information_needs_calls.append(
            kwargs.get("information_needs", ())
        )
        item = context.items[0]

        return GroundedAnswer(
            query=query,
            answer="The answer is forty-two [S1].",
            citations=(
                Citation(
                    citation_id="S1",
                    document_id=item.document_id,
                    document_title=item.document_title,
                    source_uri=item.source_uri,
                    parent_id=item.parent_id,
                    supporting_chunk_ids=("chunk-1",),
                ),
            ),
            is_grounded=True,
            abstained=False,
        )


class FakeVerifier:
    def __init__(self, supported=True):
        self.supported = supported
        self.calls = 0

    def verify(self, answer, context):
        self.calls += 1

        return VerificationResult(
            claim_checks=(),
            is_supported=self.supported,
            unsupported_claims=(
                () if self.supported else ("The answer is forty-two.",)
            ),
            confidence_reason=(
                "Supported." if self.supported else "Unsupported."
            ),
        )


class FakeWebRetriever:
    def __init__(self, context=None):
        self.context = context or make_context(empty=True)
        self.calls = []

    def retrieve(self, query):
        self.calls.append(query)
        return self.context


def make_nodes(results, *, web_context=None, verifier=None):
    settings = RagSettings(
        corrective_retrieval_limit=1,
        context_max_tokens=100,
        context_max_parents=5,
    )
    pipeline = SequencedRetrievalPipeline(results)
    rewriter = FakeRewriter()
    generator = FakeGenerator()
    web = FakeWebRetriever(web_context)
    verifier = verifier or FakeVerifier()
    context_builder = ContextBuilder(
        token_counter=WordCounter(),
        rag_settings=settings,
    )

    return (
        RagGraphNodes(
            retrieval_pipeline=pipeline,
            query_rewriter=rewriter,
            context_builder=context_builder,
            web_retriever=web,
            answer_generator=generator,
            answer_verifier=verifier,
            rag_settings=settings,
        ),
        pipeline,
        rewriter,
        generator,
        web,
        verifier,
    )


def invoke(
    nodes,
    *,
    allow_web_search=False,
    question="What is the answer?",
):
    return build_rag_graph(nodes).invoke(
        {
            "question": question,
            "conversation_context": (),
            "allow_web_search": allow_web_search,
            "route_history": (),
        }
    )


def test_sufficient_evidence_uses_fast_path():
    nodes, pipeline, rewriter, generator, web, verifier = (
        make_nodes((make_retrieval(),))
    )

    result = invoke(nodes)

    assert result["answer"].is_grounded is True
    assert result["route_history"] == (
        "retrieve",
        "generate",
        "verify",
        "finalize",
    )
    assert pipeline.calls == ["What is the answer?"]
    assert rewriter.calls == []
    assert web.calls == []
    assert verifier.calls == 1


def test_decompose_strategy_surfaces_subqueries_to_generation():
    """A decomposed question's sub-questions must reach the generator.

    Regression test for a real bug: retrieval split a question into
    subqueries and answered each independently, but that decomposition
    was discarded before generation ever saw it, so a compound
    question's second half could get silently dropped from the answer.
    """

    subqueries = (
        "Which RAG variant performed better?",
        "Why might that variant help?",
    )
    nodes, _, _, generator, _, _ = make_nodes(
        (make_retrieval(subqueries=subqueries),)
    )

    invoke(nodes)

    assert generator.information_needs_calls == [subqueries]


def test_direct_strategy_does_not_surface_information_needs():
    nodes, _, _, generator, _, _ = make_nodes((make_retrieval(),))

    invoke(nodes)

    assert generator.information_needs_calls == [()]


def test_when_should_policy_surfaces_validation_need_to_generation():
    nodes, _, _, generator, _, _ = make_nodes((make_retrieval(),))

    invoke(
        nodes,
        question="When should DARWIN use assisted parsing?",
    )

    needs = generator.information_needs_calls[0]
    assert needs[0] == "When should DARWIN use assisted parsing?"
    assert "validation" in needs[1]


def test_partial_evidence_gets_one_targeted_retry():
    nodes, pipeline, rewriter, _, _, _ = make_nodes(
        (
            make_retrieval(answerable=False),
            make_retrieval(answerable=True),
        )
    )

    result = invoke(nodes)

    assert result["answer"].is_grounded is True
    assert result["retrieval_attempts"] == 1
    assert result["route_history"] == (
        "retrieve",
        "rewrite",
        "retrieve_correction",
        "generate",
        "verify",
        "finalize",
    )
    assert len(pipeline.calls) == 2
    assert rewriter.calls == [("What is the answer?",)]


def test_irrelevant_evidence_abstains_without_web_permission():
    nodes, _, _, generator, web, verifier = make_nodes(
        (make_retrieval(answerable=False, empty=True),)
    )

    result = invoke(nodes)

    assert result["answer"].abstained is True
    assert result["route_history"] == (
        "retrieve",
        "abstain",
        "finalize",
    )
    assert generator.calls == []
    assert web.calls == []
    assert verifier.calls == 0


def test_irrelevant_evidence_can_use_approved_web_search():
    nodes, _, _, _, web, _ = make_nodes(
        (make_retrieval(answerable=False, empty=True),),
        web_context=make_context(direct=True),
    )

    result = invoke(nodes, allow_web_search=True)

    assert result["answer"].is_grounded is True
    assert result["web_used"] is True
    assert "search_web" in result["route_history"]
    assert web.calls == ["What is the answer?"]


def test_failed_verification_cannot_loop_forever():
    verifier = FakeVerifier(supported=False)
    nodes, pipeline, _, _, _, _ = make_nodes(
        (make_retrieval(answerable=True),),
        verifier=verifier,
    )

    result = invoke(nodes)

    assert result["answer"].abstained is True
    assert result["answer"].unsupported_claims == (
        "The answer is forty-two.",
    )
    assert result["retrieval_attempts"] == 0
    assert len(pipeline.calls) == 1
    assert verifier.calls == 2
    assert result["route_history"][:5] == (
        "retrieve",
        "generate",
        "verify",
        "regenerate",
        "verify",
    )
    assert result["route_history"][-2:] == (
        "abstain",
        "finalize",
    )

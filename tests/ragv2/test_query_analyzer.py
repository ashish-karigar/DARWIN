import pytest

from app.ragv2.config import RagSettings
from app.ragv2.contracts import QueryStrategy
from app.ragv2.retrieve.retrieval.query_analyzer import (
    QueryAnalyzer,
    QueryDecision as QueryDecisionContract,
)


def QueryDecision(
    *,
    standalone_query: str,
    strategy: QueryStrategy,
    subqueries=(),
    step_back_query=None,
) -> QueryDecisionContract:
    """Builds complete query-planner wire responses for tests."""

    return QueryDecisionContract(
        standalone_query=standalone_query,
        strategy=strategy,
        subqueries=tuple(subqueries),
        step_back_query=step_back_query,
    )


class FakeQueryProvider:
    def __init__(self, decision):
        self.decision = decision
        self.calls = []

    def analyze(self, query, conversation_context):
        self.calls.append(
            {
                "query": query,
                "conversation_context": tuple(
                    conversation_context
                ),
            }
        )

        return self.decision


def test_simple_question_bypasses_llm_provider():
    provider = FakeQueryProvider(
        QueryDecision(
            standalone_query="Unused",
            strategy=QueryStrategy.DIRECT,
        )
    )

    analysis = QueryAnalyzer(
        provider=provider
    ).analyze(
        "What non-parametric memory does RAG use?"
    )

    assert analysis.strategy == QueryStrategy.DIRECT
    assert analysis.standalone_query == (
        "What non-parametric memory does RAG use?"
    )
    assert provider.calls == []


def test_attribution_question_requires_authorship_and_origin_evidence():
    provider = FakeQueryProvider(
        QueryDecision(
            standalone_query="Unused",
            strategy=QueryStrategy.DIRECT,
        )
    )

    analysis = QueryAnalyzer(provider=provider).analyze(
        "Who introduced retrieval-augmented generation?"
    )

    assert analysis.strategy == QueryStrategy.DECOMPOSE
    assert analysis.subqueries == (
        (
            "Who are the credited authors associated with "
            "retrieval-augmented generation?"
        ),
        (
            "What source passage defines, names, or presents "
            "retrieval-augmented generation?"
        ),
    )
    assert provider.calls == []


def test_comparison_is_decomposed_without_an_llm_call():
    provider = FakeQueryProvider(
        QueryDecision(
            standalone_query="Unused",
            strategy=QueryStrategy.DIRECT,
        )
    )

    analysis = QueryAnalyzer(provider=provider).analyze(
        "Compare RAG-Token and RAG-Sequence."
    )

    assert analysis.strategy == QueryStrategy.DECOMPOSE
    assert analysis.subqueries == (
        "What are the defining characteristics of RAG-Token?",
        "What are the defining characteristics of RAG-Sequence?",
    )
    assert provider.calls == []


@pytest.mark.parametrize(
    "question",
    (
        "RAG-Token versus RAG-Sequence",
        "What is the difference between RAG-Token and RAG-Sequence?",
    ),
)
def test_comparison_variants_use_deterministic_decomposition(question):
    provider = FakeQueryProvider(
        QueryDecision(
            standalone_query="Unused",
            strategy=QueryStrategy.DIRECT,
        )
    )

    analysis = QueryAnalyzer(provider=provider).analyze(question)

    assert analysis.strategy == QueryStrategy.DECOMPOSE
    assert len(analysis.subqueries) == 2
    assert provider.calls == []


def test_compound_result_and_reason_is_decomposed_without_llm():
    provider = FakeQueryProvider(
        QueryDecision(
            standalone_query="Unused",
            strategy=QueryStrategy.DIRECT,
        )
    )

    analysis = QueryAnalyzer(provider=provider).analyze(
        "Which RAG variant performed better on Jeopardy question "
        "generation, and why might it help?"
    )

    assert analysis.strategy == QueryStrategy.DECOMPOSE
    assert analysis.subqueries == (
        (
            "Which RAG variant performed better on Jeopardy question "
            "generation?"
        ),
        (
            "Why might the RAG variant that performed better on "
            "Jeopardy question generation help?"
        ),
    )
    assert provider.calls == []


def test_relative_clause_that_does_not_trigger_conversation_llm():
    provider = FakeQueryProvider(
        QueryDecision(
            standalone_query="Unused",
            strategy=QueryStrategy.CONVERSATION,
        )
    )

    analysis = QueryAnalyzer(provider=provider).analyze(
        "Which clinical trial proved that DARWIN cures migraines?"
    )

    assert analysis.strategy == QueryStrategy.DIRECT
    assert provider.calls == []


def test_resolves_conversation_with_limited_history():
    provider = FakeQueryProvider(
        QueryDecision(
            standalone_query=(
                "What are the limitations of RAG?"
            ),
            strategy=QueryStrategy.CONVERSATION,
        )
    )

    analysis = QueryAnalyzer(
        provider=provider,
        rag_settings=RagSettings(
            query_analysis_history_messages=2
        ),
    ).analyze(
        "What about its limitations?",
        conversation_context=(
            "Old unrelated message",
            "We are discussing RAG.",
            "RAG uses retrieval.",
        ),
    )

    assert analysis.strategy == QueryStrategy.CONVERSATION
    assert analysis.standalone_query == (
        "What are the limitations of RAG?"
    )
    assert provider.calls[0]["conversation_context"] == (
        "We are discussing RAG.",
        "RAG uses retrieval.",
    )


def test_decomposes_compound_question():
    provider = FakeQueryProvider(
        QueryDecision(
            standalone_query=(
                "Who created DARWIN and what database "
                "does it use?"
            ),
            strategy=QueryStrategy.DECOMPOSE,
            subqueries=(
                "Who created DARWIN?",
                "What database does DARWIN use?",
            ),
        )
    )

    analysis = QueryAnalyzer(
        provider=provider
    ).analyze(
        "Who created DARWIN and what database does it use?"
    )

    assert analysis.strategy == QueryStrategy.DECOMPOSE
    assert analysis.subqueries == (
        "Who created DARWIN?",
        "What database does DARWIN use?",
    )
    assert len(provider.calls) == 1


def test_creates_step_back_query():
    provider = FakeQueryProvider(
        QueryDecision(
            standalone_query=(
                "Why does RAG reduce hallucination?"
            ),
            strategy=QueryStrategy.STEP_BACK,
            step_back_query=(
                "How do retrieval-grounded language "
                "models use external evidence?"
            ),
        )
    )

    analysis = QueryAnalyzer(
        provider=provider
    ).analyze(
        "Why does RAG reduce hallucination?"
    )

    assert analysis.strategy == QueryStrategy.STEP_BACK
    assert analysis.step_back_query is not None
    assert provider.calls == []


def test_invalid_model_plan_falls_back_to_direct_retrieval():
    provider = FakeQueryProvider(
        QueryDecisionContract.model_construct(
            standalone_query="Compound question",
            strategy=QueryStrategy.DECOMPOSE,
            subqueries=("Only one query",),
        )
    )

    analysis = QueryAnalyzer(provider=provider).analyze(
        "What is RAG and who created it?"
    )

    assert analysis.strategy == QueryStrategy.DIRECT
    assert analysis.standalone_query == (
        "What is RAG and who created it?"
    )


def test_simple_why_question_uses_deterministic_step_back_plan():
    class FailingProvider:
        def analyze(self, query, conversation_context):
            raise TimeoutError("provider unavailable")

    analysis = QueryAnalyzer(provider=FailingProvider()).analyze(
        "Why does retrieval help?"
    )

    assert analysis.strategy == QueryStrategy.STEP_BACK
    assert analysis.standalone_query == "Why does retrieval help?"
    assert analysis.step_back_query is not None


def test_hallucination_question_has_stable_step_back_fallback():
    class FailingProvider:
        def analyze(self, query, conversation_context):
            raise TimeoutError("provider unavailable")

    analysis = QueryAnalyzer(provider=FailingProvider()).analyze(
        "Why can retrieved external evidence reduce hallucination?"
    )

    assert analysis.strategy == QueryStrategy.STEP_BACK
    assert "real factual knowledge" in analysis.step_back_query
    assert "hallucination" in analysis.step_back_query


def test_rejects_empty_input():
    provider = FakeQueryProvider(
        QueryDecision(
            standalone_query="Unused",
            strategy=QueryStrategy.DIRECT,
        )
    )

    with pytest.raises(ValueError, match="cannot be empty"):
        QueryAnalyzer(provider=provider).analyze(" ")

    assert provider.calls == []


def test_uses_original_query_when_provider_omits_standalone_query():
    original_query = (
        "Who introduced RAG and what memory does it use?"
    )

    provider = FakeQueryProvider(
        QueryDecisionContract.model_construct(
            standalone_query="",
            strategy=QueryStrategy.DECOMPOSE,
            subqueries=(
                "Who introduced RAG?",
                "What memory does RAG use?",
            ),
        )
    )

    analysis = QueryAnalyzer(
        provider=provider
    ).analyze(original_query)

    assert analysis.standalone_query == original_query
    assert analysis.strategy == QueryStrategy.DECOMPOSE

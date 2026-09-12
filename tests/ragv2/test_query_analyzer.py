import pytest

from app.ragv2.config import RagSettings
from app.ragv2.contracts import QueryStrategy
from app.ragv2.retrieve.retrieval.query_analyzer import (
    QueryAnalyzer,
    QueryDecision,
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


def test_contract_rejects_invalid_decomposition():
    provider = FakeQueryProvider(
        QueryDecision(
            standalone_query="Compound question",
            strategy=QueryStrategy.DECOMPOSE,
            subqueries=("Only one query",),
        )
    )

    with pytest.raises(
        ValueError,
        match="at least two subqueries",
    ):
        QueryAnalyzer(provider=provider).analyze(
            "What is RAG and who created it?"
        )


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
        QueryDecision(
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
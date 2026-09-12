from app.ragv2.contracts import (
    ContentType,
    ContextBundle,
    ContextItem,
)
from app.ragv2.generation.answer import (
    AnswerDraft,
    GroundedAnswerGenerator,
)


class FakeAnswerProvider:
    def __init__(self, draft: AnswerDraft):
        self.draft = draft
        self.calls = []

    def generate(
        self,
        query: str,
        prompt_context: str,
    ) -> AnswerDraft:
        self.calls.append((query, prompt_context))
        return self.draft


def make_context(
    *,
    has_direct_evidence: bool = True,
) -> ContextBundle:
    item = ContextItem(
        parent_id="section-1",
        document_id="rag-paper",
        document_title="RAG Paper",
        text=(
            "RAG uses a dense vector index of Wikipedia "
            "as non-parametric memory."
        ),
        content_type=ContentType.TEXT,
        source_uri="/documents/rag-paper.pdf",
        page_number=2,
        heading_path=("Introduction",),
        supporting_chunk_ids=("chunk-1",),
        relevance_score=0.95,
        directly_answers=True,
        expanded_from_parent=True,
    )

    return ContextBundle(
        query="What memory does RAG use?",
        items=(item,),
        total_tokens=20,
        has_direct_evidence=has_direct_evidence,
    )


def test_returns_grounded_answer_with_valid_citation():
    provider = FakeAnswerProvider(
        AnswerDraft(
            answer=(
                "RAG uses a dense vector index "
                "of Wikipedia [S1]."
            ),
            citation_ids=("S1",),
        )
    )

    result = GroundedAnswerGenerator(
        provider=provider
    ).generate(
        "What memory does RAG use?",
        make_context(),
        fully_answerable=True,
    )

    assert result.is_grounded is True
    assert result.abstained is False
    assert result.citations[0].citation_id == "S1"
    assert len(provider.calls) == 1


def test_abstains_before_llm_when_question_is_not_answerable():
    provider = FakeAnswerProvider(
        AnswerDraft(
            answer="This must never be used [S1].",
            citation_ids=("S1",),
        )
    )

    result = GroundedAnswerGenerator(
        provider=provider
    ).generate(
        "Who created an unrelated system?",
        make_context(),
        fully_answerable=False,
    )

    assert result.abstained is True
    assert result.is_grounded is False
    assert provider.calls == []


def test_rejects_unknown_citation():
    provider = FakeAnswerProvider(
        AnswerDraft(
            answer="Unsupported statement [S99].",
            citation_ids=("S99",),
        )
    )

    result = GroundedAnswerGenerator(
        provider=provider
    ).generate(
        "What memory does RAG use?",
        make_context(),
        fully_answerable=True,
    )

    assert result.abstained is True
    assert "Unknown citation: S99" in (
        result.unsupported_claims
    )


def test_rejects_citation_missing_from_answer_text():
    provider = FakeAnswerProvider(
        AnswerDraft(
            answer="RAG uses a dense vector index.",
            citation_ids=("S1",),
        )
    )

    result = GroundedAnswerGenerator(
        provider=provider
    ).generate(
        "What memory does RAG use?",
        make_context(),
        fully_answerable=True,
    )

    assert result.abstained is True
    assert (
        "Citation not present in answer: S1"
        in result.unsupported_claims
    )


def test_normalizes_provider_citation_format():
    provider = FakeAnswerProvider(
        AnswerDraft(
            answer=(
                "RAG uses a dense vector index "
                "of Wikipedia【S1†L1-L2】."
            ),
            citation_ids=("S1",),
        )
    )

    result = GroundedAnswerGenerator(
        provider=provider
    ).generate(
        "What memory does RAG use?",
        make_context(),
        fully_answerable=True,
    )

    assert result.is_grounded is True
    assert result.abstained is False
    assert "[S1]" in result.answer
    assert "【S1†L1-L2】" not in result.answer
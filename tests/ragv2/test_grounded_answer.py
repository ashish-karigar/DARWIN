from app.ragv2.contracts import (
    ContentType,
    ContextBundle,
    ContextItem,
)
from app.ragv2.generation.answer import (
    AnswerDraft as AnswerDraftContract,
    GroundedAnswerGenerator,
)


def AnswerDraft(
    *,
    answer: str = "",
    citation_ids=None,
    abstained: bool = False,
    answered_queries=(),
    unanswered_queries=(),
    confidence_reason: str = "Test fixture.",
) -> AnswerDraftContract:
    """Builds complete wire responses for generator unit tests."""

    if citation_ids is None:
        citation_ids = () if abstained else ("S1",)

    return AnswerDraftContract(
        answer=answer,
        citation_ids=tuple(citation_ids),
        abstained=abstained,
        answered_queries=tuple(answered_queries),
        unanswered_queries=tuple(unanswered_queries),
        confidence_reason=confidence_reason,
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


def test_multiple_information_needs_reach_the_prompt():
    """A decompose-strategy question's sub-questions must reach the

    generator prompt -- this is the fix for a real bug where a
    compound question's second half was silently dropped because the
    generator never knew the question had been split.
    """

    provider = FakeAnswerProvider(
        AnswerDraft(
            answer="RAG-Token won. It helps because of X [S1].",
            citation_ids=("S1",),
        )
    )

    GroundedAnswerGenerator(provider=provider).generate(
        "Which variant won, and why might it help?",
        make_context(),
        fully_answerable=True,
        information_needs=(
            "Which RAG variant performed better?",
            "Why might that variant help?",
        ),
    )

    _, prompt_context = provider.calls[0]
    assert "information needs" in prompt_context.casefold()
    assert "Which RAG variant performed better?" in prompt_context
    assert "Why might that variant help?" in prompt_context


def test_single_information_need_is_not_surfaced():
    """One need is just the question itself -- nothing to enumerate.

    Also covers the default: direct/step_back/conversation strategies
    never pass information_needs, so this is what they get.
    """

    provider = FakeAnswerProvider(
        AnswerDraft(
            answer="RAG uses a dense vector index [S1].",
            citation_ids=("S1",),
        )
    )

    GroundedAnswerGenerator(provider=provider).generate(
        "What memory does RAG use?",
        make_context(),
        fully_answerable=True,
        information_needs=("What memory does RAG use?",),
    )

    _, prompt_context = provider.calls[0]
    assert "information needs" not in prompt_context.casefold()


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


def test_appends_declared_citation_missing_from_answer_text():
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

    assert result.abstained is False
    assert result.is_grounded is True
    assert result.answer.endswith("Sources: [S1]")


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


def test_normalizes_bracketed_structured_citation_id():
    provider = FakeAnswerProvider(
        AnswerDraft(
            answer="RAG uses Wikipedia [S1].",
            citation_ids=("[S1]",),
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


class SequencedAnswerProvider:
    def __init__(self, drafts):
        self.drafts = iter(drafts)
        self.call_count = 0
        self.calls = []

    def generate(self, query, prompt_context):
        self.call_count += 1
        self.calls.append((query, prompt_context))
        return next(self.drafts)


class FailingAnswerProvider:
    def generate(self, query, prompt_context):
        raise RuntimeError("Provider offline")


def test_retries_a_semantically_invalid_draft_once():
    provider = SequencedAnswerProvider(
        (
            AnswerDraft(
                abstained=True,
                confidence_reason="Uncertain.",
            ),
            AnswerDraft(
                answer="RAG uses Wikipedia [S1].",
                citation_ids=("S1",),
            ),
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
    assert provider.call_count == 2


def test_reports_provider_outage_separately_from_missing_evidence():
    result = GroundedAnswerGenerator(
        provider=FailingAnswerProvider()
    ).generate(
        "What memory does RAG use?",
        make_context(),
        fully_answerable=True,
    )

    assert result.abstained is True
    assert result.answer == (
        "I found relevant evidence, but answer generation is "
        "temporarily unavailable."
    )
    assert "provider failed" in result.confidence_reason.casefold()


def test_retry_prompt_explains_the_previous_failure():
    provider = SequencedAnswerProvider(
        (
            AnswerDraft(
                abstained=True,
                confidence_reason="Evidence relation was unclear.",
            ),
            AnswerDraft(
                answer="RAG uses Wikipedia [S1].",
                citation_ids=("S1",),
            ),
        )
    )

    GroundedAnswerGenerator(provider=provider).generate(
        "What memory does RAG use?",
        make_context(),
        fully_answerable=True,
    )

    assert "previous draft was rejected" in (
        provider.calls[1][1].casefold()
    )
    assert "relation was unclear" in (
        provider.calls[1][1].casefold()
    )


def test_returns_cited_partial_answer_after_bounded_retrieval():
    provider = FakeAnswerProvider(
        AnswerDraft(
            answer="The supported part is answered [S1].",
            citation_ids=("S1",),
            answered_queries=("Supported part",),
        )
    )

    result = GroundedAnswerGenerator(
        provider=provider
    ).generate(
        "Answer both parts",
        make_context(),
        fully_answerable=False,
        allow_partial=True,
        unanswered_queries=("Unsupported part",),
    )

    assert result.is_grounded is True
    assert result.abstained is False
    assert result.unanswered_queries == ("Unsupported part",)
    assert "Unsupported part" in provider.calls[0][1]


def test_renders_structured_calculation_without_llm():
    provider = FakeAnswerProvider(
        AnswerDraft(answer="Must not be called")
    )
    context = ContextBundle(
        query="What is the total Revenue for East?",
        items=(
            ContextItem(
                parent_id="table-1",
                document_id="sales",
                document_title="Sales",
                text=(
                    "Deterministic table calculation\n"
                    "Operation: sum\n"
                    "Column: Revenue\n"
                    "Filters: Region = East\n"
                    "Matched rows: 2\n"
                    "Result: 2700.5\n"
                    "Input rows:\nRegion: East | Revenue: 2700.5"
                ),
                content_type=ContentType.TABLE,
                source_uri="/sales.md",
                supporting_chunk_ids=("structured:table-1",),
                relevance_score=1.0,
                directly_answers=True,
                expanded_from_parent=False,
            ),
        ),
        total_tokens=20,
        has_direct_evidence=True,
    )

    result = GroundedAnswerGenerator(
        provider=provider
    ).generate(
        context.query,
        context,
        fully_answerable=True,
    )

    assert result.answer == (
        "The total Revenue where Region = East is 2700.5 [S1]."
    )
    assert result.is_grounded is True
    assert provider.calls == []

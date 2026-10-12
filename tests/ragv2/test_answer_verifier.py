from app.ragv2.contracts import (
    Citation,
    ContentType,
    ContextBundle,
    ContextItem,
    GroundedAnswer,
)
from app.ragv2.generation.verifier import (
    AnswerVerifier,
    ClaimDecision as ClaimDecisionContract,
)


def ClaimDecision(
    *,
    claim: str,
    citation_ids,
    support_score: float,
    supported: bool,
    reason: str,
    contradicted: bool = False,
) -> ClaimDecisionContract:
    """Builds complete wire decisions for verifier unit tests."""

    return ClaimDecisionContract(
        claim=claim,
        citation_ids=tuple(citation_ids),
        support_score=support_score,
        supported=supported,
        contradicted=contradicted,
        reason=reason,
    )


class FakeVerificationProvider:
    def __init__(self, decisions):
        self.decisions = decisions
        self.calls = []

    def verify(self, query, answer, prompt_context):
        self.calls.append((query, answer, prompt_context))
        return self.decisions


class FakeEmbeddingModel:
    """Deterministic stand-in for the real Ollama embedding client.

    Keeps semantic-tier tests offline and independent of hardware --
    they assert on cosine similarity behavior, not on what a live
    embedding model happens to return.
    """

    model_name = "fake-embed"

    def __init__(self, vectors: dict[str, list[float]]):
        self.vectors = vectors

    def embed_documents(self, texts):
        return [self.vectors[text] for text in texts]

    def embed_query(self, text):
        return self.vectors[text]


class RaisingEmbeddingModel:
    """Simulates the embedding service being unavailable."""

    model_name = "raising-embed"

    def embed_documents(self, texts):
        raise RuntimeError("embedding service unavailable")

    def embed_query(self, text):
        raise RuntimeError("embedding service unavailable")


def make_context() -> ContextBundle:
    return ContextBundle(
        query="What memory does RAG use?",
        items=(
            ContextItem(
                parent_id="section-1",
                document_id="rag-paper",
                document_title="RAG Paper",
                text=(
                    "RAG uses a dense Wikipedia vector index."
                ),
                content_type=ContentType.TEXT,
                source_uri="/rag-paper.pdf",
                page_number=2,
                supporting_chunk_ids=("chunk-1",),
                relevance_score=0.95,
                directly_answers=True,
                expanded_from_parent=True,
            ),
        ),
        total_tokens=10,
        has_direct_evidence=True,
    )


def make_answer(*, abstained=False) -> GroundedAnswer:
    citations = (
        ()
        if abstained
        else (
            Citation(
                citation_id="S1",
                document_id="rag-paper",
                document_title="RAG Paper",
                source_uri="/rag-paper.pdf",
                page_number=2,
                parent_id="section-1",
                supporting_chunk_ids=("chunk-1",),
            ),
        )
    )

    return GroundedAnswer(
        query="What memory does RAG use?",
        answer=(
            "I do not have enough evidence."
            if abstained
            else "RAG uses a Wikipedia vector index [S1]."
        ),
        citations=citations,
        is_grounded=not abstained,
        abstained=abstained,
    )


def test_accepts_supported_claim_with_known_citation():
    provider = FakeVerificationProvider(
        (
            ClaimDecision(
                claim="RAG uses a Wikipedia vector index.",
                citation_ids=("S1",),
                support_score=0.96,
                supported=True,
                reason="The source states this directly.",
            ),
        )
    )

    result = AnswerVerifier(provider=provider).verify(
        make_answer(),
        make_context(),
    )

    assert result.is_supported is True
    assert result.unsupported_claims == ()


def test_verifies_exact_single_claim_without_model_call():
    provider = FakeVerificationProvider(())
    answer = make_answer().model_copy(
        update={
            "answer": (
                "RAG uses a dense Wikipedia vector index. Sources: [S1]"
            )
        }
    )

    result = AnswerVerifier(provider=provider).verify(
        answer,
        make_context(),
    )

    assert result.is_supported is True
    assert result.claim_checks[0].support_score == 1.0
    assert provider.calls == []


def test_verifies_high_overlap_paraphrase_without_model_call():
    provider = FakeVerificationProvider(())

    result = AnswerVerifier(provider=provider).verify(
        make_answer(),
        make_context(),
    )

    assert result.is_supported is True
    assert result.claim_checks[0].support_score == 1.0
    assert "lexical support" in result.claim_checks[0].reason
    assert provider.calls == []


def test_verifies_literal_comparison_without_model_call():
    provider = FakeVerificationProvider(())
    context = ContextBundle(
        query="Compare RAG-Token and RAG-Sequence.",
        items=(
            ContextItem(
                parent_id="comparison-section",
                document_id="rag-paper",
                document_title="RAG Paper",
                text=(
                    "RAG-Sequence uses the same document to predict each "
                    "target token. RAG-Token can predict each target token "
                    "based on a different document."
                ),
                content_type=ContentType.TEXT,
                source_uri="/rag-paper.pdf",
                page_number=3,
                supporting_chunk_ids=("comparison-chunk",),
                relevance_score=0.99,
                directly_answers=True,
                expanded_from_parent=True,
            ),
        ),
        total_tokens=30,
        has_direct_evidence=True,
    )
    answer = GroundedAnswer(
        query=context.query,
        answer=(
            "RAG-Sequence uses the same document to predict each target "
            "token [S1]. RAG-Token can predict each target token based on "
            "a different document [S1]."
        ),
        citations=(
            Citation(
                citation_id="S1",
                document_id="rag-paper",
                document_title="RAG Paper",
                source_uri="/rag-paper.pdf",
                page_number=3,
                parent_id="comparison-section",
                supporting_chunk_ids=("comparison-chunk",),
            ),
        ),
        is_grounded=True,
        abstained=False,
    )

    result = AnswerVerifier(provider=provider).verify(answer, context)

    assert result.is_supported is True
    assert len(result.claim_checks) == 2
    assert provider.calls == []


def test_does_not_fast_path_changed_numeric_value():
    provider = FakeVerificationProvider(
        (
            ClaimDecision(
                claim="The index has 22 million vectors.",
                citation_ids=("S1",),
                support_score=0.1,
                supported=False,
                reason="The cited evidence does not contain that value.",
            ),
        )
    )
    context = make_context().model_copy(
        update={
            "items": (
                make_context().items[0].model_copy(
                    update={"text": "The index has 21 million vectors."}
                ),
            )
        }
    )
    answer = make_answer().model_copy(
        update={"answer": "The index has 22 million vectors [S1]."}
    )

    result = AnswerVerifier(provider=provider).verify(answer, context)

    assert result.is_supported is False
    assert len(provider.calls) == 1


def test_rejects_unknown_citation_even_if_model_approves():
    provider = FakeVerificationProvider(
        (
            ClaimDecision(
                claim="RAG uses a Wikipedia vector index.",
                citation_ids=("S99",),
                support_score=0.99,
                supported=True,
                reason="Claimed support.",
            ),
        )
    )

    answer = make_answer().model_copy(
        update={"answer": "RAG relies on a hidden source [S1]."}
    )

    result = AnswerVerifier(provider=provider).verify(
        answer,
        make_context(),
    )

    assert result.is_supported is False


def test_restores_inline_citation_for_one_unambiguous_claim():
    provider = FakeVerificationProvider(
        (
            ClaimDecision(
                claim="RAG uses Wikipedia.",
                citation_ids=(),
                support_score=0.95,
                supported=True,
                reason="The evidence supports the claim.",
            ),
        )
    )
    answer = make_answer()
    context = make_context()
    answer = answer.model_copy(
        update={"answer": "RAG uses Wikipedia. Sources: [S1]"}
    )

    result = AnswerVerifier(provider=provider).verify(
        answer,
        context,
    )

    assert result.is_supported is True
    assert result.claim_checks[0].citation_ids == ("S1",)


def test_does_not_guess_citations_for_multiple_claims():
    provider = FakeVerificationProvider(
        (
            ClaimDecision(
                claim="Claim one.",
                citation_ids=(),
                support_score=1.0,
                supported=True,
                reason="Supported.",
            ),
            ClaimDecision(
                claim="Claim two.",
                citation_ids=(),
                support_score=1.0,
                supported=True,
                reason="Supported.",
            ),
        )
    )
    answer = make_answer()
    context = make_context()
    answer = answer.model_copy(
        update={
            "answer": "Claim one. Claim two. Sources: [S1]"
        }
    )

    result = AnswerVerifier(provider=provider).verify(
        answer,
        context,
    )

    assert result.is_supported is False
    assert len(result.unsupported_claims) == 2
    assert result.unsupported_claims


def test_restores_distinct_citations_for_multiple_matching_claims():
    provider = FakeVerificationProvider(
        (
            ClaimDecision(
                claim="RAG-Token may use a different document per token.",
                citation_ids=(),
                support_score=0.98,
                supported=True,
                reason="The evidence states this directly.",
            ),
            ClaimDecision(
                claim="RAG-Sequence uses the same document for every token.",
                citation_ids=(),
                support_score=0.97,
                supported=True,
                reason="The evidence states this directly.",
            ),
        )
    )
    context = ContextBundle(
        query="Compare RAG-Token and RAG-Sequence.",
        items=(
            ContextItem(
                parent_id="token-section",
                document_id="rag-paper",
                document_title="RAG Paper",
                text=(
                    "RAG-Token can use a different document for each "
                    "target token."
                ),
                content_type=ContentType.TEXT,
                source_uri="/rag-paper.pdf",
                page_number=3,
                supporting_chunk_ids=("token-chunk",),
                relevance_score=0.99,
                directly_answers=True,
                expanded_from_parent=True,
            ),
            ContextItem(
                parent_id="sequence-section",
                document_id="rag-paper",
                document_title="RAG Paper",
                text=(
                    "RAG-Sequence uses the same document to predict "
                    "each target token."
                ),
                content_type=ContentType.TEXT,
                source_uri="/rag-paper.pdf",
                page_number=3,
                supporting_chunk_ids=("sequence-chunk",),
                relevance_score=0.98,
                directly_answers=True,
                expanded_from_parent=True,
            ),
        ),
        total_tokens=30,
        has_direct_evidence=True,
    )
    answer = GroundedAnswer(
        query=context.query,
        answer=(
            "RAG-Token may use a different document per token. "
            "RAG-Sequence uses the same document for every token. "
            "Sources: [S1] [S2]"
        ),
        citations=(
            Citation(
                citation_id="S1",
                document_id="rag-paper",
                document_title="RAG Paper",
                source_uri="/rag-paper.pdf",
                page_number=3,
                parent_id="token-section",
                supporting_chunk_ids=("token-chunk",),
            ),
            Citation(
                citation_id="S2",
                document_id="rag-paper",
                document_title="RAG Paper",
                source_uri="/rag-paper.pdf",
                page_number=3,
                parent_id="sequence-section",
                supporting_chunk_ids=("sequence-chunk",),
            ),
        ),
        is_grounded=True,
        abstained=False,
    )

    result = AnswerVerifier(provider=provider).verify(answer, context)

    assert result.is_supported is True
    assert result.claim_checks[0].citation_ids == ("S1",)
    assert result.claim_checks[1].citation_ids == ("S2",)


def test_reports_contradicted_claim_separately():
    provider = FakeVerificationProvider(
        (
            ClaimDecision(
                claim="RAG uses no external memory.",
                citation_ids=("S1",),
                support_score=0.05,
                supported=False,
                contradicted=True,
                reason="The source states the opposite.",
            ),
        )
    )

    answer = make_answer().model_copy(
        update={"answer": "RAG uses no external memory [S1]."}
    )

    result = AnswerVerifier(provider=provider).verify(
        answer,
        make_context(),
    )

    assert result.is_supported is False
    assert result.contradicted_claims == (
        "RAG uses no external memory.",
    )


def test_abstention_skips_model_verification():
    provider = FakeVerificationProvider(())

    result = AnswerVerifier(provider=provider).verify(
        make_answer(abstained=True),
        make_context(),
    )

    assert result.is_supported is True
    assert provider.calls == []


def test_verifies_structured_calculation_without_llm():
    provider = FakeVerificationProvider(())
    context = ContextBundle(
        query="What is the total?",
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
                    "Result: 2700.5"
                ),
                content_type=ContentType.TABLE,
                source_uri="/sales.md",
                supporting_chunk_ids=("structured:table-1",),
                relevance_score=1.0,
                directly_answers=True,
                expanded_from_parent=False,
            ),
        ),
        total_tokens=12,
        has_direct_evidence=True,
    )
    answer = GroundedAnswer(
        query=context.query,
        answer="The total Revenue is 2700.5 [S1].",
        citations=(
            Citation(
                citation_id="S1",
                document_id="sales",
                document_title="Sales",
                source_uri="/sales.md",
                parent_id="table-1",
                supporting_chunk_ids=("structured:table-1",),
            ),
        ),
        is_grounded=True,
        abstained=False,
    )

    result = AnswerVerifier(provider=provider).verify(
        answer,
        context,
    )

    assert result.is_supported is True
    assert result.claim_checks[0].support_score == 1.0
    assert provider.calls == []


def test_deterministically_verifies_multiple_claims_with_trailing_citations():
    """Assigns each claim to its supporting trailing citation locally."""

    provider = FakeVerificationProvider(())
    claim_1 = "RAG-Token draws a different document for each generated token."
    claim_2 = (
        "RAG-Sequence keeps one retrieved passage fixed for the whole output."
    )
    evidence_1 = (
        "RAG-Token can draw a different latent document for each "
        "generated token."
    )
    evidence_2 = (
        "RAG-Sequence keeps one retrieved passage fixed for the whole "
        "output."
    )
    context = ContextBundle(
        query="Compare RAG-Token and RAG-Sequence.",
        items=(
            ContextItem(
                parent_id="token-section",
                document_id="rag-paper",
                document_title="RAG Paper",
                text=evidence_1,
                content_type=ContentType.TEXT,
                source_uri="/rag-paper.pdf",
                page_number=3,
                supporting_chunk_ids=("token-chunk",),
                relevance_score=0.99,
                directly_answers=True,
                expanded_from_parent=True,
            ),
            ContextItem(
                parent_id="sequence-section",
                document_id="rag-paper",
                document_title="RAG Paper",
                text=evidence_2,
                content_type=ContentType.TEXT,
                source_uri="/rag-paper.pdf",
                page_number=3,
                supporting_chunk_ids=("sequence-chunk",),
                relevance_score=0.98,
                directly_answers=True,
                expanded_from_parent=True,
            ),
        ),
        total_tokens=30,
        has_direct_evidence=True,
    )
    answer = GroundedAnswer(
        query=context.query,
        answer=f"{claim_1} {claim_2} Sources: [S1] [S2]",
        citations=(
            Citation(
                citation_id="S1",
                document_id="rag-paper",
                document_title="RAG Paper",
                source_uri="/rag-paper.pdf",
                page_number=3,
                parent_id="token-section",
                supporting_chunk_ids=("token-chunk",),
            ),
            Citation(
                citation_id="S2",
                document_id="rag-paper",
                document_title="RAG Paper",
                source_uri="/rag-paper.pdf",
                page_number=3,
                parent_id="sequence-section",
                supporting_chunk_ids=("sequence-chunk",),
            ),
        ),
        is_grounded=True,
        abstained=False,
    )

    result = AnswerVerifier(provider=provider).verify(answer, context)

    assert result.is_supported is True
    assert result.claim_checks[0].citation_ids == ("S1",)
    assert result.claim_checks[1].citation_ids == ("S2",)
    assert "lexical support" in result.claim_checks[0].reason
    assert provider.calls == []


def test_semantic_tier_still_rejects_changed_numeric_value():
    """A near-identical embedding must not override a changed number."""

    provider = FakeVerificationProvider(
        (
            ClaimDecision(
                claim="The index has 22 million vectors.",
                citation_ids=("S1",),
                support_score=0.1,
                supported=False,
                reason="The cited evidence does not contain that value.",
            ),
        )
    )
    claim = "The index has 22 million vectors."
    evidence = "The index has 21 million vectors."
    embedding_model = FakeEmbeddingModel(
        {claim: [1.0, 0.0], evidence: [1.0, 0.0]}
    )
    context = make_context().model_copy(
        update={
            "items": (
                make_context().items[0].model_copy(
                    update={"text": evidence}
                ),
            )
        }
    )
    answer = make_answer().model_copy(
        update={"answer": f"{claim} [S1]."}
    )

    result = AnswerVerifier(
        provider=provider,
        embedding_model=embedding_model,
    ).verify(answer, context)

    assert result.is_supported is False
    assert len(provider.calls) == 1


def test_semantic_tier_failure_falls_through_to_model():
    """An unavailable embedding service must not break verification."""

    provider = FakeVerificationProvider(
        (
            ClaimDecision(
                claim="RAG uses a Wikipedia vector index.",
                citation_ids=("S1",),
                support_score=0.9,
                supported=True,
                reason="The source states this directly.",
            ),
        )
    )
    answer = make_answer().model_copy(
        update={"answer": "RAG relies on a hidden source [S1]."}
    )

    result = AnswerVerifier(
        provider=provider,
        embedding_model=RaisingEmbeddingModel(),
    ).verify(answer, make_context())

    assert result.is_supported is True
    assert len(provider.calls) == 1

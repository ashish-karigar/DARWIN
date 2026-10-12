import pytest

from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    Chunk,
    ContentType,
    RetrievalHit,
)
from app.ragv2.retrieve.retrieval.grader import (
    EvidenceDecision,
    EvidenceGrader,
)


def create_hit(
    chunk_id: str,
    rank: int,
) -> RetrievalHit:
    return RetrievalHit(
        chunk=Chunk(
            chunk_id=chunk_id,
            document_id="document-1",
            parent_id=f"parent-{chunk_id}",
            text=f"Evidence contained in {chunk_id}.",
            content_type=ContentType.TEXT,
            source_uri="/documents/rag.pdf",
            token_count=5,
        ),
        score=0.9,
        rank=rank,
        retriever="reranker",
    )


class FakeGradingProvider:
    def __init__(self, decisions):
        self.decisions = tuple(decisions)
        self.calls = []

    def grade(self, query, hits):
        self.calls.append(
            {
                "query": query,
                "hits": tuple(hits),
            }
        )

        return self.decisions


def test_distinguishes_direct_related_and_weak_evidence():
    hits = (
        create_hit("direct", 1),
        create_hit("related", 2),
        create_hit("weak", 3),
    )

    provider = FakeGradingProvider(
        (
            EvidenceDecision(
                chunk_id="related",
                relevance_score=0.85,
                is_relevant=True,
                directly_answers=False,
                reason="Related background only.",
            ),
            EvidenceDecision(
                chunk_id="direct",
                relevance_score=0.97,
                is_relevant=True,
                directly_answers=True,
                reason="Explicitly states the answer.",
            ),
            EvidenceDecision(
                chunk_id="weak",
                relevance_score=0.40,
                is_relevant=True,
                directly_answers=True,
                reason="Insufficient supporting detail.",
            ),
        )
    )

    grades = EvidenceGrader(
        provider=provider,
        rag_settings=RagSettings(
            evidence_relevance_threshold=0.65
        ),
    ).grade(
        "What memory does RAG use?",
        hits,
    )

    assert [grade.hit.chunk.chunk_id for grade in grades] == [
        "direct",
        "related",
        "weak",
    ]

    assert grades[0].is_relevant
    assert grades[0].directly_answers

    assert grades[1].is_relevant
    assert not grades[1].directly_answers

    assert not grades[2].is_relevant
    assert not grades[2].directly_answers


def test_empty_hits_skip_the_provider():
    provider = FakeGradingProvider(())
    grader = EvidenceGrader(provider=provider)

    assert grader.grade("A valid question", ()) == ()
    assert provider.calls == []


def test_rejects_duplicate_input_chunks():
    hit = create_hit("duplicate", 1)
    grader = EvidenceGrader(
        provider=FakeGradingProvider(())
    )

    with pytest.raises(
        ValueError,
        match="duplicate chunk IDs",
    ):
        grader.grade("Question", (hit, hit))


@pytest.mark.parametrize(
    "decisions",
    [
        (),
        (
            EvidenceDecision(
                chunk_id="unknown",
                relevance_score=0.9,
                is_relevant=True,
                directly_answers=True,
                reason="Unknown result.",
            ),
        ),
        (
            EvidenceDecision(
                chunk_id="expected",
                relevance_score=0.9,
                is_relevant=True,
                directly_answers=True,
                reason="First decision.",
            ),
            EvidenceDecision(
                chunk_id="expected",
                relevance_score=0.8,
                is_relevant=True,
                directly_answers=False,
                reason="Duplicate decision.",
            ),
        ),
    ],
)
def test_invalid_provider_responses_fail_closed(decisions):
    grader = EvidenceGrader(
        provider=FakeGradingProvider(decisions)
    )

    grades = grader.grade(
        "Question",
        (create_hit("expected", 1),),
    )

    assert grades[0].is_relevant is False
    assert grades[0].directly_answers is False
    assert "missing, duplicate, or unknown" in grades[0].reason


def test_rejects_empty_question():
    grader = EvidenceGrader(
        provider=FakeGradingProvider(())
    )

    with pytest.raises(ValueError, match="cannot be empty"):
        grader.grade("   ", ())


def test_provider_failure_fails_closed_without_crashing():
    class FailingProvider:
        def grade(self, query, hits):
            raise TimeoutError("provider unavailable")

    grades = EvidenceGrader(
        provider=FailingProvider()
    ).grade(
        "Question",
        (create_hit("expected", 1),),
    )

    assert len(grades) == 1
    assert grades[0].is_relevant is False
    assert grades[0].directly_answers is False
    assert "TimeoutError" in grades[0].reason


def test_default_grader_accepts_answer_shaped_local_result_without_llm():
    grader = EvidenceGrader(
        rag_settings=RagSettings(
            enable_llm_evidence_grading=False
        )
    )
    hits = (
        create_hit("direct", 1).model_copy(
            update={
                "score": 0.97,
                "chunk": create_hit("direct", 1).chunk.model_copy(
                    update={"text": "The total amount is $475.25."}
                ),
            }
        ),
        create_hit("weak", 2).model_copy(
            update={"score": 0.20}
        ),
    )

    grades = grader.grade("What is the total amount?", hits)

    assert grades[0].directly_answers is True
    assert grades[1].is_relevant is False
    assert grader.provider is None


def test_default_grader_can_accept_direct_evidence_below_top_three():
    """The acceptance cap must not also become a scan-depth cap."""

    hits = tuple(
        create_hit(f"hit-{rank}", rank).model_copy(
            update={
                "chunk": create_hit(f"hit-{rank}", rank).chunk.model_copy(
                    update={
                        "text": (
                            "Retrieval-augmented generation is a grounded "
                            "generation method."
                            if rank == 4
                            else "An unrelated author-list fragment."
                        )
                    }
                )
            }
        )
        for rank in range(1, 6)
    )
    grader = EvidenceGrader(
        rag_settings=RagSettings(
            enable_llm_evidence_grading=False,
            evidence_fast_path_limit=3,
        )
    )

    grades = grader.grade(
        "What source passage defines retrieval-augmented generation?",
        hits,
    )

    assert grades[3].directly_answers is True


def test_default_grader_rejects_decisively_weak_results_without_llm():
    grader = EvidenceGrader(
        rag_settings=RagSettings(
            enable_llm_evidence_grading=False
        )
    )
    hits = (
        create_hit("weak", 1).model_copy(
            update={"score": 0.01}
        ),
    )

    grades = grader.grade("Question", hits)

    assert grades[0].is_relevant is False
    assert grader.provider is None


def test_default_grader_does_not_call_generic_related_text_direct():
    grader = EvidenceGrader(
        rag_settings=RagSettings(
            enable_llm_evidence_grading=False
        )
    )
    hit = create_hit("mid-confidence", 1).model_copy(
        update={"score": 0.72}
    )

    grades = grader.grade("Question", (hit,))

    assert grades[0].directly_answers is False
    assert grades[0].is_relevant is False
    assert grader.provider is None


def test_corroborated_but_related_passage_goes_to_evidence_judge():
    hit = create_hit("related", 1).model_copy(
        update={
            "chunk": create_hit("related", 1).chunk.model_copy(
                update={
                    "text": (
                        "RAG-Sequence achieved a strong score on the "
                        "Jeopardy benchmark."
                    )
                }
            ),
            "metadata": {
                "matched_retrievers": ("vector", "lexical"),
                "previous_score": 0.95,
                "component_scores": {
                    "vector": 0.70,
                    "lexical": 0.60,
                },
            },
        }
    )
    provider = FakeGradingProvider(
        (
            EvidenceDecision(
                chunk_id="related",
                relevance_score=0.8,
                is_relevant=True,
                directly_answers=False,
                reason="Performance is related but does not define it.",
            ),
        )
    )

    grades = EvidenceGrader(
        provider=provider,
        enable_confidence_shortcuts=True,
    ).grade(
        "What are the defining characteristics of RAG-Sequence?",
        (hit,),
    )

    assert grades[0].is_relevant is True
    assert grades[0].directly_answers is False
    assert len(provider.calls) == 1


def test_low_reranker_score_uses_strong_hybrid_corroboration():
    base = create_hit("corroborated", 1)
    hit = base.model_copy(
        update={
            "score": 0.02,
            "chunk": base.chunk.model_copy(
                update={"text": "The total amount is $475.25."}
            ),
            "metadata": {
                "matched_retrievers": ("vector", "lexical"),
                "previous_score": 0.91,
                "component_scores": {
                    "vector": 0.64,
                    "lexical": 0.51,
                },
            },
        }
    )
    provider = FakeGradingProvider(
        (
            EvidenceDecision(
                chunk_id="corroborated",
                relevance_score=0.95,
                is_relevant=True,
                directly_answers=True,
                reason="The passage answers the question.",
            ),
        )
    )
    grader = EvidenceGrader(
        provider=provider,
        enable_confidence_shortcuts=True,
    )

    grades = grader.grade(
        "What is the total amount?",
        (hit,),
    )

    assert grades[0].directly_answers is True
    assert provider.calls == []


def test_corroborated_evidence_uses_full_context_capacity():
    """A defining passage must not be lost behind three topical hits."""

    hits = []

    for index in range(5):
        base = create_hit(f"comparison-{index}", index + 1)
        hits.append(
            base.model_copy(
                update={
                    "chunk": base.chunk.model_copy(
                        update={
                            "text": (
                                "RAG-Token uses a different passage for "
                                "each token, while RAG-Sequence uses one "
                                "passage for the sequence. "
                                f"Corroborated passage {index + 1}."
                            )
                        }
                    ),
                    "metadata": {
                        "matched_retrievers": ("vector", "lexical"),
                        "previous_score": 0.95 - (index * 0.01),
                        "component_scores": {
                            "vector": 0.70,
                            "lexical": 0.60,
                        },
                    },
                }
            )
        )

    provider = FakeGradingProvider(())
    grades = EvidenceGrader(
        provider=provider,
        rag_settings=RagSettings(
            evidence_fast_path_limit=3,
            evidence_corroborated_limit=5,
        ),
        enable_confidence_shortcuts=True,
    ).grade(
        "Compare RAG-Token and RAG-Sequence.",
        tuple(hits),
    )

    assert len([grade for grade in grades if grade.directly_answers]) == 5
    assert grades[3].directly_answers is True
    assert provider.calls == []


def test_comparison_template_words_are_not_evidence_anchors():
    """Routing language must not hide an explicit entity definition."""

    hit = create_hit("rag-token-definition", 1).model_copy(
        update={
            "chunk": create_hit(
                "rag-token-definition",
                1,
            ).chunk.model_copy(
                update={
                    "text": (
                        "In the RAG-Token model, a different latent "
                        "document can be drawn for each target token."
                    )
                }
            ),
            "score": 0.95,
            "metadata": {
                "matched_retrievers": ("vector", "lexical"),
                "previous_score": 0.95,
                "component_scores": {
                    "vector": 0.70,
                    "lexical": 0.60,
                },
            },
        }
    )
    provider = FakeGradingProvider(())
    grades = EvidenceGrader(
        provider=provider,
        enable_confidence_shortcuts=True,
    ).grade(
        "What are the defining characteristics of RAG-Token?",
        (hit,),
    )

    assert grades[0].directly_answers is True
    assert provider.calls == []


@pytest.mark.parametrize(
    ("question", "passage"),
    [
        (
            "How much tax was charged on invoice DARWIN-2048?",
            "Invoice DARWIN-2048 has a total of $475.25.",
        ),
        (
            "What is the total Revenue for the North region?",
            "Region East has Revenue of $1,200.50.",
        ),
    ],
)
def test_hybrid_near_match_does_not_bypass_judge(
    question,
    passage,
):
    hit = create_hit("near-match", 1).model_copy(
        update={
            "chunk": create_hit("near-match", 1).chunk.model_copy(
                update={"text": passage}
            ),
            "score": 0.95,
            "metadata": {
                "matched_retrievers": ("vector", "lexical"),
                "previous_score": 0.95,
                "component_scores": {
                    "vector": 0.70,
                    "lexical": 0.60,
                },
            },
        }
    )
    provider = FakeGradingProvider(
        (
            EvidenceDecision(
                chunk_id="near-match",
                relevance_score=0.7,
                is_relevant=True,
                directly_answers=False,
                reason="The requested value is absent.",
            ),
        )
    )

    grades = EvidenceGrader(
        provider=provider,
        enable_confidence_shortcuts=True,
    ).grade(question, (hit,))

    assert grades[0].is_relevant is True
    assert grades[0].directly_answers is False
    assert len(provider.calls) == 1


def test_hybrid_shortcut_uses_heading_as_evidence_anchor():
    base = create_hit("authors", 1)
    hit = base.model_copy(
        update={
            "chunk": base.chunk.model_copy(
                update={
                    "text": "Patrick Lewis and Ethan Perez",
                    "heading_path": (
                        "Retrieval-Augmented Generation",
                    ),
                }
            ),
            "score": 0.99,
            "metadata": {
                "matched_retrievers": ("vector", "lexical"),
                "previous_score": 0.95,
                "component_scores": {
                    "vector": 0.70,
                    "lexical": 0.60,
                },
            },
        }
    )
    provider = FakeGradingProvider(())

    grades = EvidenceGrader(
        provider=provider,
        enable_confidence_shortcuts=True,
    ).grade(
        "Who are the credited authors associated with "
        "retrieval-augmented generation?",
        (hit,),
    )

    assert grades[0].directly_answers is True
    assert provider.calls == []


def test_normalized_hybrid_rank_without_absolute_scores_is_rejected():
    hit = create_hit("weak-corroboration", 1).model_copy(
        update={
            "score": 0.02,
            "metadata": {
                "matched_retrievers": ("vector", "lexical"),
                "previous_score": 1.0,
                "component_scores": {
                    "vector": 0.55,
                    "lexical": 0.52,
                },
            },
        }
    )
    provider = FakeGradingProvider(
        (
            EvidenceDecision(
                chunk_id="weak-corroboration",
                relevance_score=0.2,
                is_relevant=False,
                directly_answers=False,
                reason="The absolute dense score is weak.",
            ),
        )
    )
    grader = EvidenceGrader(
        provider=provider,
        enable_confidence_shortcuts=True,
    )

    grades = grader.grade("Question", (hit,))

    assert grades[0].directly_answers is False
    assert provider.calls == []


@pytest.mark.parametrize(
    ("question", "passage"),
    [
        (
            "Which RAG variant performed better on Jeopardy?",
            "RAG-Token performs better than RAG-Sequence on Jeopardy.",
        ),
        (
            "What non-parametric memory does RAG use?",
            "RAG uses a dense vector index as non-parametric memory.",
        ),
    ],
)
def test_what_and_which_answers_can_use_deterministic_fast_path(
    question,
    passage,
):
    base = create_hit("direct", 1)
    hit = base.model_copy(
        update={
            "chunk": base.chunk.model_copy(update={"text": passage}),
            "score": 0.95,
            "metadata": {
                "matched_retrievers": ("vector", "lexical"),
                "previous_score": 0.95,
                "component_scores": {
                    "vector": 0.70,
                    "lexical": 0.60,
                },
            },
        }
    )
    provider = FakeGradingProvider(())

    grades = EvidenceGrader(
        provider=provider,
        enable_confidence_shortcuts=True,
    ).grade(question, (hit,))

    assert grades[0].directly_answers is True
    assert provider.calls == []


@pytest.mark.parametrize(
    ("question", "passage"),
    [
        (
            "How does being grounded in real factual knowledge affect "
            "hallucination and factual generation?",
            "Being strongly grounded in real factual knowledge makes "
            "the model hallucinate less and produce more factual "
            "generations.",
        ),
        (
            "Which parser should DARWIN primarily use for PDF files?",
            "| Input | Primary parser | Escalation path |\n"
            "| PDF | Docling | LlamaParse |",
        ),
    ],
)
def test_local_grader_accepts_causal_and_policy_paraphrases(
    question,
    passage,
):
    base = create_hit("direct-local-evidence", 1)
    hit = base.model_copy(
        update={
            "chunk": base.chunk.model_copy(
                update={"text": passage}
            )
        }
    )

    grader = EvidenceGrader(
        rag_settings=RagSettings(
            enable_llm_evidence_grading=False
        )
    )
    grades = grader.grade(question, (hit,))

    assert grader.provider is None
    assert grades[0].is_relevant is True
    assert grades[0].directly_answers is True


@pytest.mark.parametrize(
    ("question", "passage"),
    [
        (
            "How much tax was charged on invoice DARWIN-2048?",
            "Invoice DARWIN-2048 has a total of $475.25.",
        ),
        (
            "What is the total Revenue for the North region?",
            "Region East has Revenue of $1,200.50.",
        ),
    ],
)
def test_local_grader_rejects_missing_requested_fact(
    question,
    passage,
):
    base = create_hit("local-near-match", 1)
    hit = base.model_copy(
        update={
            "chunk": base.chunk.model_copy(
                update={"text": passage}
            )
        }
    )

    grades = EvidenceGrader(
        rag_settings=RagSettings(
            enable_llm_evidence_grading=False
        )
    ).grade(question, (hit,))

    assert grades[0].is_relevant is False
    assert grades[0].directly_answers is False


def test_local_grader_ignores_question_scaffolding_for_numeric_policy():
    passage = (
        "After drafting an answer, retrieve again only for a specific "
        "missing claim. The workflow must be bounded. One corrective "
        "retrieval and one correction pass are enough for the first "
        "version."
    )
    base = create_hit("correction-policy", 1)
    hit = base.model_copy(
        update={
            "chunk": base.chunk.model_copy(
                update={"text": passage}
            )
        }
    )

    grades = EvidenceGrader(
        rag_settings=RagSettings(
            enable_llm_evidence_grading=False
        )
    ).grade(
        "How many corrective retrieval passes are allowed in the "
        "first RAG version?",
        (hit,),
    )

    assert grades[0].is_relevant is True
    assert grades[0].directly_answers is True

from app.ragv2.contracts import WebSearchResult
from app.ragv2.retrieve.retrieval.rewriter import (
    CorrectiveQueryRewriter,
    RewriteDecision,
)
from app.ragv2.retrieve.retrieval.web import (
    WebEvidenceRetriever,
)


class FakeRewriteProvider:
    def rewrite(self, original_question, target_queries):
        return (
            RewriteDecision(
                target_query=target_queries[0],
                rewritten_query=(
                    "retrieval-augmented generation authors"
                ),
            ),
        )


class FailingRewriteProvider:
    def rewrite(self, original_question, target_queries):
        raise RuntimeError("Unavailable")


def test_rewrites_only_the_missing_query():
    result = CorrectiveQueryRewriter(
        provider=FakeRewriteProvider()
    ).rewrite(
        "Who introduced RAG and what memory does it use?",
        ("Who introduced RAG?",),
    )

    assert result == (
        "retrieval-augmented generation authors",
    )


def test_rewriter_falls_back_to_original_target():
    result = CorrectiveQueryRewriter(
        provider=FailingRewriteProvider()
    ).rewrite(
        "Question",
        ("Missing fact",),
    )

    assert result == ("Missing fact",)


class FakeWebProvider:
    def search(self, query, limit):
        return (
            WebSearchResult(
                title="Authoritative source",
                url="https://example.com/source",
                text="The direct answer is forty-two.",
                score=0.9,
            ),
        )


class DirectEvidenceGrader:
    def grade(self, query, hits):
        from app.ragv2.contracts import EvidenceGrade

        return tuple(
            EvidenceGrade(
                hit=hit,
                relevance_score=0.95,
                is_relevant=True,
                directly_answers=True,
                reason="Direct web evidence.",
            )
            for hit in hits
        )


def test_web_results_become_citable_context():
    context = WebEvidenceRetriever(
        provider=FakeWebProvider(),
        evidence_grader=DirectEvidenceGrader(),
    ).retrieve("What is the answer?")

    assert context.has_direct_evidence is True
    assert context.items[0].source_uri == (
        "https://example.com/source"
    )
    assert context.items[0].document_title == (
        "Authoritative source"
    )

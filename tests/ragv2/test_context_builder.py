from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    Chunk,
    ContentType,
    DocumentSection,
    EvidenceGrade,
    ParsedDocument,
    RetrievalHit,
    SourceType,
    ContextBundle,
    ContextItem,
)
from app.ragv2.retrieve.retrieval.context_builder import (
    ContextBuilder,
)


class FakeDocumentStore:
    def __init__(self, document=None, parents=None):
        self.document = document
        self.parents = parents or {}

    def get_document(self, document_id):
        if (
            self.document is not None
            and self.document.document_id == document_id
        ):
            return self.document

        return None

    def get_parent(self, parent_id):
        return self.parents.get(parent_id)


class WordTokenCounter:
    def count(self, text):
        return len(text.split())

    def truncate(self, text, maximum_tokens):
        return " ".join(
            text.split()[:maximum_tokens]
        )


def create_document() -> ParsedDocument:
    return ParsedDocument(
        document_id="document-1",
        title="RAG Paper",
        source_type=SourceType.PDF,
        source_uri="/documents/rag.pdf",
        sections=(
            DocumentSection(
                section_id="parent-direct",
                text=(
                    "The non-parametric memory is a "
                    "dense Wikipedia vector index."
                ),
                heading_path=("Introduction",),
                page_number=2,
            ),
            DocumentSection(
                section_id="parent-related",
                text=(
                    "Non-parametric memory can be "
                    "updated at test time."
                ),
                heading_path=("Discussion",),
                page_number=7,
            ),
        ),
    )


def create_grade(
    chunk_id,
    parent_id,
    rank,
    relevance,
    directly_answers,
    is_relevant=True,
    document_id="document-1",
):
    return EvidenceGrade(
        hit=RetrievalHit(
            chunk=Chunk(
                chunk_id=chunk_id,
                document_id=document_id,
                parent_id=parent_id,
                text=f"Child evidence {chunk_id}.",
                content_type=ContentType.TEXT,
                source_uri="/documents/rag.pdf",
                token_count=4,
                metadata={
                    "document_title": "RAG Paper"
                },
            ),
            score=0.9,
            rank=rank,
            retriever="reranker",
        ),
        relevance_score=relevance,
        is_relevant=is_relevant,
        directly_answers=directly_answers,
        reason="Controlled test decision.",
    )


def create_builder(
    rag_settings=None,
    document=True,
    parents=True,
):
    parsed_document = (
        create_document()
        if document
        else None
    )

    parent_mapping = (
        {
            section.section_id: section
            for section in create_document().sections
        }
        if parents
        else {}
    )

    return ContextBuilder(
        document_store=FakeDocumentStore(
            document=parsed_document,
            parents=parent_mapping,
        ),
        token_counter=WordTokenCounter(),
        rag_settings=(
            rag_settings
            or RagSettings(
                context_max_tokens=100,
                context_max_parents=5,
            )
        ),
    )


def test_filters_orders_expands_and_deduplicates():
    grades = (
        create_grade(
            "related-child",
            "parent-related",
            rank=1,
            relevance=0.90,
            directly_answers=False,
        ),
        create_grade(
            "direct-child",
            "parent-direct",
            rank=2,
            relevance=0.95,
            directly_answers=True,
        ),
        create_grade(
            "direct-child-two",
            "parent-direct",
            rank=3,
            relevance=0.80,
            directly_answers=True,
        ),
        create_grade(
            "rejected-child",
            "parent-rejected",
            rank=4,
            relevance=0.20,
            directly_answers=False,
            is_relevant=False,
        ),
    )

    bundle = create_builder().build(
        "What memory does RAG use?",
        grades,
    )

    assert len(bundle.items) == 2
    assert bundle.has_direct_evidence

    direct_item = bundle.items[0]

    assert direct_item.parent_id == "parent-direct"
    assert direct_item.page_number == 2
    assert direct_item.heading_path == ("Introduction",)
    assert direct_item.expanded_from_parent
    assert not direct_item.truncated
    assert direct_item.supporting_chunk_ids == (
        "direct-child",
        "direct-child-two",
    )


def test_enforces_token_budget_by_truncating_parent():
    bundle = create_builder(
        rag_settings=RagSettings(
            context_max_tokens=5,
            context_max_parents=5,
        )
    ).build(
        "What memory does RAG use?",
        (
            create_grade(
                "direct-child",
                "parent-direct",
                rank=1,
                relevance=0.95,
                directly_answers=True,
            ),
        ),
    )

    assert bundle.total_tokens == 5
    assert bundle.items[0].truncated
    assert len(bundle.items[0].text.split()) == 5
    assert bundle.has_direct_evidence


def test_falls_back_to_child_when_parent_is_missing():
    bundle = create_builder(
        document=False,
        parents=False,
    ).build(
        "Question",
        (
            create_grade(
                "fallback-child",
                "missing-parent",
                rank=1,
                relevance=0.90,
                directly_answers=True,
            ),
        ),
    )

    item = bundle.items[0]

    assert item.text == "Child evidence fallback-child."
    assert item.document_title == "RAG Paper"
    assert not item.expanded_from_parent


def test_reports_when_direct_evidence_is_missing():
    bundle = create_builder().build(
        "What memory does RAG use?",
        (
            create_grade(
                "related-child",
                "parent-related",
                rank=1,
                relevance=0.90,
                directly_answers=False,
            ),
        ),
    )

    assert len(bundle.items) == 1
    assert not bundle.has_direct_evidence


def test_rejoins_short_adjacent_pdf_fragments_and_deduplicates():
    document = ParsedDocument(
        document_id="paper",
        title="A Research Paper",
        source_type=SourceType.PDF,
        source_uri="/documents/paper.pdf",
        sections=(
            DocumentSection(
                section_id="authors-1",
                text="Ada Lovelace,",
                heading_path=("A Research Paper",),
                page_number=1,
            ),
            DocumentSection(
                section_id="authors-2",
                text="Grace Hopper, Alan Turing",
                heading_path=("A Research Paper",),
                page_number=1,
            ),
            DocumentSection(
                section_id="abstract",
                text="A long abstract begins here.",
                heading_path=("Abstract",),
                page_number=1,
            ),
        ),
    )
    parents = {
        section.section_id: section
        for section in document.sections
    }
    builder = ContextBuilder(
        document_store=FakeDocumentStore(
            document=document,
            parents=parents,
        ),
        token_counter=WordTokenCounter(),
        rag_settings=RagSettings(
            context_max_tokens=100,
            context_max_parents=5,
            context_fragment_max_tokens=10,
            context_fragment_window=2,
            context_fragment_group_max_tokens=20,
        ),
    )
    grades = (
        create_grade(
            "authors-child-1",
            "authors-1",
            rank=1,
            relevance=0.99,
            directly_answers=True,
            document_id="paper",
        ),
        create_grade(
            "authors-child-2",
            "authors-2",
            rank=2,
            relevance=0.98,
            directly_answers=True,
            document_id="paper",
        ),
    )

    bundle = builder.build("Who wrote the paper?", grades)

    assert len(bundle.items) == 1
    assert bundle.items[0].text == (
        "Ada Lovelace,\nGrace Hopper, Alan Turing"
    )
    assert bundle.has_direct_evidence


def test_merges_retry_context_and_deduplicates_parents():
    builder = create_builder()

    original = ContextBundle(
        query="Question",
        items=(
            ContextItem(
                parent_id="shared",
                document_id="document-1",
                document_title="RAG Paper",
                text="Initial supporting evidence.",
                content_type=ContentType.TEXT,
                source_uri="/documents/rag.pdf",
                supporting_chunk_ids=("old",),
                relevance_score=0.70,
                directly_answers=False,
                expanded_from_parent=True,
            ),
        ),
        total_tokens=3,
        has_direct_evidence=False,
    )
    correction = ContextBundle(
        query="Rewritten question",
        items=(
            original.items[0].model_copy(
                update={
                    "text": "Corrected direct evidence.",
                    "supporting_chunk_ids": ("new",),
                    "relevance_score": 0.95,
                    "directly_answers": True,
                }
            ),
        ),
        total_tokens=3,
        has_direct_evidence=True,
    )

    merged = builder.merge(
        "Question",
        (original, correction),
    )

    assert len(merged.items) == 1
    assert merged.items[0].text == "Corrected direct evidence."
    assert merged.has_direct_evidence is True


def test_merge_prefers_source_diversity_before_backfill():
    builder = create_builder(
        rag_settings=RagSettings(
            context_max_tokens=100,
            context_max_parents=3,
            context_preferred_parents_per_document=1,
        )
    )

    def item(document_id, parent_id, score):
        return ContextItem(
            parent_id=parent_id,
            document_id=document_id,
            document_title=document_id,
            text=f"Evidence from {parent_id}.",
            content_type=ContentType.TEXT,
            source_uri=f"/{document_id}.txt",
            supporting_chunk_ids=(parent_id,),
            relevance_score=score,
            directly_answers=True,
            expanded_from_parent=True,
        )

    bundle = ContextBundle(
        query="Question",
        items=(
            item("document-a", "a-1", 0.99),
            item("document-a", "a-2", 0.98),
            item("document-b", "b-1", 0.90),
        ),
        total_tokens=9,
        has_direct_evidence=True,
    )

    merged = builder.merge("Question", (bundle,))

    assert [value.parent_id for value in merged.items] == [
        "a-1",
        "b-1",
        "a-2",
    ]


class MultiDocumentStore:
    """A document store spanning more than one document, for testing

    build_requirements() with sub-questions from different sources.
    """

    def __init__(self, documents, parents):
        self.documents = documents
        self.parents = parents

    def get_document(self, document_id):
        return self.documents.get(document_id)

    def get_parent(self, parent_id):
        return self.parents.get(parent_id)


def test_build_requirements_preserves_evidence_from_every_document():
    """Two sub-questions on two different documents must both survive.

    Regression test for a real cross-document decompose bug: a
    sub-question's own well-graded evidence can be reserved correctly
    per-requirement and still never reach the final answer if nothing
    guards it through the merge step. build_requirements() previously
    had zero test coverage with 2+ requirements, so this exact
    "evidence for one sub-question disappears" failure mode would not
    have been caught.
    """

    parser_document = ParsedDocument(
        document_id="plan-doc",
        title="Build Plan",
        source_type=SourceType.PDF,
        source_uri="/documents/plan.pdf",
        sections=(
            DocumentSection(
                section_id="parser-parent",
                text="DARWIN uses Docling as the primary PDF parser.",
                heading_path=("Parsing",),
                page_number=1,
            ),
        ),
    )
    memory_document = ParsedDocument(
        document_id="rag-doc",
        title="RAG Paper",
        source_type=SourceType.PDF,
        source_uri="/documents/rag.pdf",
        sections=(
            DocumentSection(
                section_id="memory-parent",
                text=(
                    "RAG's non-parametric memory is a dense "
                    "Wikipedia vector index."
                ),
                heading_path=("Memory",),
                page_number=2,
            ),
        ),
    )
    store = MultiDocumentStore(
        documents={
            "plan-doc": parser_document,
            "rag-doc": memory_document,
        },
        parents={
            "parser-parent": parser_document.sections[0],
            "memory-parent": memory_document.sections[0],
        },
    )
    builder = ContextBuilder(
        document_store=store,
        token_counter=WordTokenCounter(),
        rag_settings=RagSettings(
            context_max_tokens=100,
            context_max_parents=5,
            context_parents_per_requirement=3,
        ),
    )
    parser_grades = (
        create_grade(
            "parser-child",
            "parser-parent",
            rank=1,
            relevance=0.9,
            directly_answers=True,
            document_id="plan-doc",
        ),
    )
    memory_grades = (
        create_grade(
            "memory-child",
            "memory-parent",
            rank=1,
            relevance=0.9,
            directly_answers=True,
            document_id="rag-doc",
        ),
    )

    bundle = builder.build_requirements(
        "Which parser should DARWIN use, and what memory does RAG use?",
        (
            ("Which parser should DARWIN use?", parser_grades),
            ("What memory does RAG use?", memory_grades),
        ),
    )

    document_ids = {item.document_id for item in bundle.items}
    assert document_ids == {"plan-doc", "rag-doc"}


def test_build_requirements_reserves_distinct_evidence_per_need():
    """A shared top hit must not hide a second need's direct evidence."""

    builder = create_builder(
        rag_settings=RagSettings(
            context_max_tokens=100,
            context_max_parents=5,
            context_parents_per_requirement=1,
        )
    )
    winner = create_grade(
        "winner-child",
        "parent-direct",
        rank=1,
        relevance=1.0,
        directly_answers=True,
    )
    reason = create_grade(
        "reason-child",
        "parent-related",
        rank=2,
        relevance=0.99,
        directly_answers=True,
    )

    bundle = builder.build_requirements(
        "Which variant won and why?",
        (
            ("Which variant won?", (winner,)),
            ("Why did that variant help?", (winner, reason)),
        ),
    )

    assert [item.parent_id for item in bundle.items] == [
        "parent-direct",
        "parent-related",
    ]
    assert bundle.items[0].information_needs == (
        "Which variant won?",
    )
    assert bundle.items[1].information_needs == (
        "Why did that variant help?",
    )

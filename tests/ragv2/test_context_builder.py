from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    Chunk,
    ContentType,
    DocumentSection,
    EvidenceGrade,
    ParsedDocument,
    RetrievalHit,
    SourceType,
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
):
    return EvidenceGrade(
        hit=RetrievalHit(
            chunk=Chunk(
                chunk_id=chunk_id,
                document_id="document-1",
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
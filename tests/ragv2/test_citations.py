from app.ragv2.contracts import (
    ContentType,
    ContextBundle,
    ContextItem,
)
from app.ragv2.generation.citations import (
    CitationBuilder,
)


def make_context_item(
    parent_id: str,
    page_number: int,
) -> ContextItem:
    return ContextItem(
        parent_id=parent_id,
        document_id="rag-paper",
        document_title="RAG Paper",
        text="Retrieved evidence from the paper.",
        content_type=ContentType.TEXT,
        source_uri="/documents/rag-paper.pdf",
        page_number=page_number,
        heading_path=("Introduction",),
        supporting_chunk_ids=(f"{parent_id}-child",),
        relevance_score=0.95,
        directly_answers=True,
        expanded_from_parent=True,
    )


def test_builds_numbered_citations_with_provenance():
    context = ContextBundle(
        query="What memory does RAG use?",
        items=(
            make_context_item("parent-1", 1),
            make_context_item("parent-2", 2),
        ),
        total_tokens=20,
        has_direct_evidence=True,
    )

    result = CitationBuilder().build(context)

    assert tuple(
        citation.citation_id
        for citation in result.citations
    ) == ("S1", "S2")

    assert result.citations[0].page_number == 1
    assert result.citations[0].parent_id == "parent-1"
    assert "[S1]" in result.prompt_context
    assert "Document: RAG Paper" in result.prompt_context
    assert "Heading: Introduction" in result.prompt_context
    assert "Retrieved evidence" in result.prompt_context


def test_empty_context_produces_no_citations():
    context = ContextBundle(
        query="Unknown question",
        items=(),
        total_tokens=0,
        has_direct_evidence=False,
    )

    result = CitationBuilder().build(context)

    assert result.citations == ()
    assert result.prompt_context == ""
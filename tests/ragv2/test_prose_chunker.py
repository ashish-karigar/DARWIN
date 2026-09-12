from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.chunking.prose import ProseChunker


def create_document() -> tuple[ParsedDocument, str]:
    text = (
        "Production retrieval systems preserve document structure. "
        "Child chunks improve search precision. "
        "Parent sections restore context for grounded answers. "
        "Stable identifiers make ingestion deterministic. "
    ) * 4

    document = ParsedDocument(
        document_id="document-1",
        title="Production RAG",
        source_type=SourceType.TEXT,
        source_uri="/documents/rag.txt",
        sections=(
            DocumentSection(
                section_id="section-1",
                text=text,
                heading_path=("Retrieval",),
                start_offset=100,
                end_offset=100 + len(text),
            ),
        ),
    )

    return document, text


def test_creates_bounded_child_chunks():
    document, _ = create_document()

    chunker = ProseChunker(
        RagSettings(
            child_chunk_tokens=20,
            child_chunk_overlap_tokens=5,
        )
    )

    chunks = chunker.chunk(document)

    assert len(chunks) > 1
    assert all(chunk.token_count <= 20 for chunk in chunks)
    assert all(chunk.parent_id == "section-1" for chunk in chunks)
    assert all(chunk.heading_path == ("Retrieval",) for chunk in chunks)


def test_preserves_source_offsets():
    document, original_text = create_document()

    chunks = ProseChunker(
        RagSettings(
            child_chunk_tokens=20,
            child_chunk_overlap_tokens=5,
        )
    ).chunk(document)

    for chunk in chunks:
        relative_start = chunk.start_offset - 100
        relative_end = chunk.end_offset - 100

        assert original_text[relative_start:relative_end] == chunk.text


def test_chunk_ids_are_deterministic():
    document, _ = create_document()
    chunker = ProseChunker()

    first_run = chunker.chunk(document)
    second_run = chunker.chunk(document)

    assert [chunk.chunk_id for chunk in first_run] == [
        chunk.chunk_id for chunk in second_run
    ]
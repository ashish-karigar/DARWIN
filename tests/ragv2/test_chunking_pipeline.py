import pytest

from app.ragv2.contracts import (
    ContentType,
    DocumentSection,
    DocumentTable,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.chunking.pipeline import ChunkingPipeline


def create_document() -> ParsedDocument:
    return ParsedDocument(
        document_id="document-1",
        title="Production RAG",
        source_type=SourceType.PDF,
        source_uri="/documents/rag.pdf",
        sections=(
            DocumentSection(
                section_id="section-1",
                text="Child chunks improve retrieval precision.",
                heading_path=("Retrieval",),
                page_number=1,
            ),
        ),
        tables=(
            DocumentTable(
                table_id="table-1",
                markdown=(
                    "| Metric | Score |\n"
                    "|---|---:|\n"
                    "| Hit@3 | 100% |"
                ),
                caption="Evaluation results",
                page_number=2,
            ),
        ),
    )


def test_combines_all_registered_chunkers():
    result = ChunkingPipeline().chunk(create_document())

    assert result.document_id == "document-1"
    assert len(result.chunks) == 2

    assert {chunk.content_type for chunk in result.chunks} == {
        ContentType.TEXT,
        ContentType.TABLE,
    }

    assert {chunk.parent_id for chunk in result.chunks} == {
        "section-1",
        "table-1",
    }

    assert result.total_tokens > 0


def test_chunk_ids_are_unique():
    result = ChunkingPipeline().chunk(create_document())

    chunk_ids = [chunk.chunk_id for chunk in result.chunks]

    assert len(chunk_ids) == len(set(chunk_ids))


def test_rejects_empty_chunker_collection():
    with pytest.raises(
        ValueError,
        match="requires at least one chunker",
    ):
        ChunkingPipeline(chunkers=())
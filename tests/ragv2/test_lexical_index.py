from pathlib import Path

import pytest

from app.ragv2.contracts import Chunk, ContentType
from app.ragv2.ingest.indexes.lexical import (
    SQLiteLexicalIndex,
)


def create_chunks() -> tuple[Chunk, ...]:
    return (
        Chunk(
            chunk_id="error-code",
            document_id="document-a",
            parent_id="section-error",
            text=(
                "Error code DARWIN-2048 indicates an "
                "expired authorization token."
            ),
            content_type=ContentType.TEXT,
            source_uri="/documents/errors.txt",
            token_count=10,
        ),
        Chunk(
            chunk_id="retrieval",
            document_id="document-a",
            parent_id="section-retrieval",
            text=(
                "Semantic retrieval finds conceptually "
                "related evidence."
            ),
            content_type=ContentType.TEXT,
            source_uri="/documents/rag.txt",
            token_count=7,
        ),
        Chunk(
            chunk_id="invoice",
            document_id="document-b",
            parent_id="table-invoice",
            text=(
                "Invoice number ZX-991 has a total "
                "of 475 dollars."
            ),
            content_type=ContentType.TABLE,
            source_uri="/documents/invoice.pdf",
            token_count=11,
        ),
    )


def create_index(tmp_path: Path) -> SQLiteLexicalIndex:
    return SQLiteLexicalIndex(
        tmp_path / "lexical.sqlite3"
    )


def test_finds_exact_identifier(tmp_path: Path):
    index = create_index(tmp_path)
    index.upsert(create_chunks())

    hits = index.search("What does DARWIN-2048 mean?")

    assert hits[0].chunk.chunk_id == "error-code"
    assert hits[0].retriever == "lexical"
    assert hits[0].rank == 1
    assert hits[0].score == 1.0


def test_matches_stemmed_word_variants(tmp_path: Path):
    index = create_index(tmp_path)
    index.upsert(create_chunks())

    hits = index.search("retrieving evidence")

    assert hits[0].chunk.chunk_id == "retrieval"


def test_filters_by_document_and_content_type(
    tmp_path: Path,
):
    index = create_index(tmp_path)
    index.upsert(create_chunks())

    hits = index.search(
        "invoice total",
        document_id="document-b",
        content_type=ContentType.TABLE,
    )

    assert len(hits) == 1
    assert hits[0].chunk.chunk_id == "invoice"


def test_upserts_and_deletes_by_document(tmp_path: Path):
    index = create_index(tmp_path)
    chunks = create_chunks()

    index.upsert(chunks)
    index.upsert(chunks)

    assert index.count() == 3
    assert index.delete_document("document-a") == 2
    assert index.count() == 1
    assert index.delete_document("missing") == 0


def test_handles_unsearchable_and_invalid_queries(
    tmp_path: Path,
):
    index = create_index(tmp_path)
    index.upsert(create_chunks())

    assert index.search("!!!") == ()

    with pytest.raises(ValueError, match="cannot be empty"):
        index.search("   ")

    with pytest.raises(ValueError, match="must be positive"):
        index.search("retrieval", limit=0)
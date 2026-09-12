from app.ragv2.contracts import Chunk, ContentType
from app.ragv2.ingest.indexes.search_text import (
    build_search_text,
)


def test_enriches_search_text_without_changing_chunk():
    chunk = Chunk(
        chunk_id="author-chunk",
        document_id="rag-paper",
        parent_id="author-section",
        text="Patrick Lewis, Ethan Perez, and colleagues.",
        content_type=ContentType.TEXT,
        heading_path=(
            "Retrieval-Augmented Generation "
            "for Knowledge-Intensive NLP Tasks",
        ),
        source_uri="/documents/rag-paper.pdf",
        token_count=8,
        metadata={
            "document_title": "RAG Paper",
        },
    )

    search_text = build_search_text(chunk)

    assert "Document: RAG Paper" in search_text
    assert "Section: Retrieval-Augmented Generation" in search_text
    assert "Patrick Lewis" in search_text

    assert chunk.text == (
        "Patrick Lewis, Ethan Perez, and colleagues."
    )
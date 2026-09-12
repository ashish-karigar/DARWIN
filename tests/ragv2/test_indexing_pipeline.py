import pytest

from app.ragv2.contracts import (
    Chunk,
    ContentType,
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.indexes.pipeline import (
    IndexingPipeline,
)


class FakeDocumentStore:
    def __init__(self):
        self.documents = {}

    def store(self, document):
        self.documents[document.document_id] = document

    def get_document(self, document_id):
        return self.documents.get(document_id)

    def get_parent(self, parent_id):
        return None

    def delete(self, document_id):
        return self.documents.pop(document_id, None) is not None


class FakeChildIndex:
    def __init__(self):
        self.chunks = {}

    def upsert(self, chunks):
        for chunk in chunks:
            self.chunks[chunk.chunk_id] = chunk

    def delete_document(self, document_id):
        matching_ids = [
            chunk_id
            for chunk_id, chunk in self.chunks.items()
            if chunk.document_id == document_id
        ]

        for chunk_id in matching_ids:
            del self.chunks[chunk_id]

        return len(matching_ids)


def create_document() -> ParsedDocument:
    return ParsedDocument(
        document_id="document-1",
        title="Production RAG",
        source_type=SourceType.TEXT,
        source_uri="/documents/rag.txt",
        sections=(
            DocumentSection(
                section_id="section-1",
                text="Hybrid retrieval improves recall.",
            ),
        ),
    )


def create_chunk(
    chunk_id: str,
    document_id: str = "document-1",
    token_count: int = 5,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        parent_id="section-1",
        text=f"Searchable content for {chunk_id}.",
        content_type=ContentType.TEXT,
        source_uri="/documents/rag.txt",
        token_count=token_count,
    )


def create_pipeline():
    document_store = FakeDocumentStore()
    vector_index = FakeChildIndex()
    lexical_index = FakeChildIndex()

    pipeline = IndexingPipeline(
        document_store=document_store,
        vector_index=vector_index,
        lexical_index=lexical_index,
    )

    return (
        pipeline,
        document_store,
        vector_index,
        lexical_index,
    )


def test_indexes_every_representation():
    pipeline, document_store, vector_index, lexical_index = (
        create_pipeline()
    )
    document = create_document()
    chunks = (
        create_chunk("chunk-1", token_count=5),
        create_chunk("chunk-2", token_count=7),
    )

    result = pipeline.index(document, chunks)

    assert result.document_id == "document-1"
    assert result.chunk_count == 2
    assert result.token_count == 12
    assert result.replaced_vector_chunks == 0
    assert result.replaced_lexical_chunks == 0

    assert document_store.get_document("document-1") == document
    assert set(vector_index.chunks) == {"chunk-1", "chunk-2"}
    assert set(lexical_index.chunks) == {"chunk-1", "chunk-2"}


def test_reindexing_removes_stale_chunks():
    pipeline, _, vector_index, lexical_index = create_pipeline()
    document = create_document()

    pipeline.index(
        document,
        (
            create_chunk("old-1"),
            create_chunk("old-2"),
        ),
    )

    result = pipeline.index(
        document,
        (create_chunk("new-1"),),
    )

    assert result.replaced_vector_chunks == 2
    assert result.replaced_lexical_chunks == 2
    assert set(vector_index.chunks) == {"new-1"}
    assert set(lexical_index.chunks) == {"new-1"}


def test_deletes_every_representation():
    pipeline, document_store, vector_index, lexical_index = (
        create_pipeline()
    )

    pipeline.index(
        create_document(),
        (
            create_chunk("chunk-1"),
            create_chunk("chunk-2"),
        ),
    )

    result = pipeline.delete("document-1")

    assert result.document_existed
    assert result.deleted_vector_chunks == 2
    assert result.deleted_lexical_chunks == 2
    assert document_store.documents == {}
    assert vector_index.chunks == {}
    assert lexical_index.chunks == {}


def test_rejects_invalid_chunk_collection():
    pipeline, _, _, _ = create_pipeline()
    document = create_document()

    with pytest.raises(
        ValueError,
        match="without searchable chunks",
    ):
        pipeline.index(document, ())

    with pytest.raises(
        ValueError,
        match="must belong",
    ):
        pipeline.index(
            document,
            (
                create_chunk(
                    "wrong-document",
                    document_id="document-2",
                ),
            ),
        )
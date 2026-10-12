from collections.abc import Sequence
from dataclasses import dataclass

from app.ragv2.contracts import Chunk, ParsedDocument
from app.ragv2.ingest.indexes.document_store import (
    DocumentStore,
    SQLiteDocumentStore,
)
from app.ragv2.ingest.indexes.lexical import (
    LexicalIndex,
    SQLiteLexicalIndex,
)
from app.ragv2.ingest.indexes.vector import (
    ChromaVectorIndex,
    VectorIndex,
)
from app.ragv2.ingest.indexes.structured import (
    SQLiteStructuredIndex,
    StructuredIndex,
)


@dataclass(frozen=True, slots=True)
class IndexingResult:
    document_id: str
    chunk_count: int
    token_count: int
    replaced_vector_chunks: int
    replaced_lexical_chunks: int
    structured_row_count: int = 0
    replaced_structured_rows: int = 0


@dataclass(frozen=True, slots=True)
class DeletionResult:
    document_id: str
    document_existed: bool
    deleted_vector_chunks: int
    deleted_lexical_chunks: int
    deleted_structured_rows: int = 0


class IndexingPipeline:
    """Writes one parsed document to every searchable representation."""

    def __init__(
        self,
        document_store: DocumentStore | None = None,
        vector_index: VectorIndex | None = None,
        lexical_index: LexicalIndex | None = None,
        structured_index: StructuredIndex | None = None,
    ):
        self.document_store = (
            document_store or SQLiteDocumentStore()
        )
        self.vector_index = (
            vector_index or ChromaVectorIndex()
        )
        self.lexical_index = (
            lexical_index or SQLiteLexicalIndex()
        )
        self.structured_index = (
            structured_index or SQLiteStructuredIndex()
        )

    def index(
        self,
        document: ParsedDocument,
        chunks: Sequence[Chunk],
    ) -> IndexingResult:
        chunks = tuple(chunks)

        if not chunks:
            raise ValueError(
                "Cannot index a document without searchable chunks."
            )

        if any(
            chunk.document_id != document.document_id
            for chunk in chunks
        ):
            raise ValueError(
                "Every chunk must belong to the indexed document."
            )

        replaced_vector_chunks = (
            self.vector_index.delete_document(
                document.document_id
            )
        )
        replaced_lexical_chunks = (
            self.lexical_index.delete_document(
                document.document_id
            )
        )
        replaced_structured_rows = (
            self.structured_index.delete_document(
                document.document_id
            )
        )

        self.document_store.store(document)
        self.vector_index.upsert(chunks)
        self.lexical_index.upsert(chunks)
        structured_row_count = self.structured_index.upsert(
            document
        )

        return IndexingResult(
            document_id=document.document_id,
            chunk_count=len(chunks),
            token_count=sum(
                chunk.token_count for chunk in chunks
            ),
            replaced_vector_chunks=replaced_vector_chunks,
            replaced_lexical_chunks=replaced_lexical_chunks,
            structured_row_count=structured_row_count,
            replaced_structured_rows=replaced_structured_rows,
        )

    def delete(
        self,
        document_id: str,
    ) -> DeletionResult:
        deleted_vector_chunks = (
            self.vector_index.delete_document(document_id)
        )
        deleted_lexical_chunks = (
            self.lexical_index.delete_document(document_id)
        )
        deleted_structured_rows = (
            self.structured_index.delete_document(document_id)
        )
        document_existed = self.document_store.delete(
            document_id
        )

        return DeletionResult(
            document_id=document_id,
            document_existed=document_existed,
            deleted_vector_chunks=deleted_vector_chunks,
            deleted_lexical_chunks=deleted_lexical_chunks,
            deleted_structured_rows=deleted_structured_rows,
        )

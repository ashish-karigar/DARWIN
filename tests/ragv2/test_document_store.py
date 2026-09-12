from pathlib import Path

from app.ragv2.contracts import (
    DocumentImage,
    DocumentSection,
    DocumentTable,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.indexes.document_store import (
    SQLiteDocumentStore,
)


def create_document() -> ParsedDocument:
    return ParsedDocument(
        document_id="document-1",
        title="Production RAG",
        source_type=SourceType.PDF,
        source_uri="/documents/rag.pdf",
        sections=(
            DocumentSection(
                section_id="section-1",
                text="Child retrieval improves precision.",
                page_number=1,
            ),
        ),
        tables=(
            DocumentTable(
                table_id="table-1",
                markdown="| Metric | Score |\n|---|---|\n| Hit@3 | 100% |",
                page_number=2,
            ),
        ),
        images=(
            DocumentImage(
                image_id="image-1",
                caption="RAG architecture",
                page_number=3,
            ),
        ),
    )


def test_persists_and_restores_complete_document(
    tmp_path: Path,
):
    store = SQLiteDocumentStore(tmp_path / "documents.sqlite3")
    document = create_document()

    store.store(document)

    assert store.get_document(document.document_id) == document
    assert store.count_documents() == 1


def test_retrieves_each_parent_directly(tmp_path: Path):
    store = SQLiteDocumentStore(tmp_path / "documents.sqlite3")
    store.store(create_document())

    assert store.get_parent("section-1").text == (
        "Child retrieval improves precision."
    )
    assert store.get_parent("table-1").page_number == 2
    assert store.get_parent("image-1").caption == (
        "RAG architecture"
    )
    assert store.get_parent("missing-parent") is None


def test_replaces_stale_parents_when_document_changes(
    tmp_path: Path,
):
    store = SQLiteDocumentStore(tmp_path / "documents.sqlite3")
    store.store(create_document())

    updated_document = ParsedDocument(
        document_id="document-1",
        title="Updated RAG",
        source_type=SourceType.TEXT,
        source_uri="/documents/rag.txt",
        sections=(
            DocumentSection(
                section_id="section-2",
                text="Updated parent content.",
            ),
        ),
    )

    store.store(updated_document)

    assert store.count_documents() == 1
    assert store.get_parent("section-1") is None
    assert store.get_parent("section-2").text == (
        "Updated parent content."
    )


def test_delete_cascades_to_parents(tmp_path: Path):
    store = SQLiteDocumentStore(tmp_path / "documents.sqlite3")
    store.store(create_document())

    assert store.delete("document-1")
    assert store.get_document("document-1") is None
    assert store.get_parent("section-1") is None
    assert store.count_documents() == 0
    assert not store.delete("missing-document")
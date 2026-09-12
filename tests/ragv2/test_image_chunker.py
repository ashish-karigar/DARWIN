from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    ContentType,
    DocumentImage,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.chunking.images import ImageChunker


def create_document() -> ParsedDocument:
    return ParsedDocument(
        document_id="document-1",
        title="RAG Architecture",
        source_type=SourceType.PDF,
        source_uri="/documents/rag.pdf",
        images=(
            DocumentImage(
                image_id="image-1",
                caption="Production RAG architecture",
                description=(
                    "The diagram shows parsing, chunking, indexing, "
                    "retrieval, reranking, and grounded generation. "
                ) * 5,
                heading_path=("Architecture",),
                page_number=3,
                path_or_url="/images/architecture.png",
            ),
            DocumentImage(
                image_id="image-2",
                page_number=4,
                path_or_url="/images/decorative.png",
            ),
        ),
    )


def test_creates_searchable_image_description_chunks():
    chunks = ImageChunker(
        RagSettings(
            child_chunk_tokens=30,
            child_chunk_overlap_tokens=5,
        )
    ).chunk(create_document())

    assert len(chunks) > 1
    assert all(
        chunk.content_type == ContentType.IMAGE_DESCRIPTION
        for chunk in chunks
    )
    assert all(chunk.parent_id == "image-1" for chunk in chunks)
    assert all(chunk.page_number == 3 for chunk in chunks)
    assert all(chunk.token_count <= 30 for chunk in chunks)
    assert all(
        chunk.metadata["image_path"]
        == "/images/architecture.png"
        for chunk in chunks
    )


def test_skips_images_without_caption_or_description():
    chunks = ImageChunker().chunk(
        ParsedDocument(
            document_id="document-2",
            title="Decorative image",
            source_type=SourceType.IMAGE,
            source_uri="/images/decorative.png",
            images=(
                DocumentImage(
                    image_id="image-1",
                    path_or_url="/images/decorative.png",
                ),
            ),
        )
    )

    assert chunks == ()


def test_chunk_ids_are_deterministic():
    document = create_document()
    chunker = ImageChunker()

    first_run = chunker.chunk(document)
    second_run = chunker.chunk(document)

    assert [chunk.chunk_id for chunk in first_run] == [
        chunk.chunk_id for chunk in second_run
    ]
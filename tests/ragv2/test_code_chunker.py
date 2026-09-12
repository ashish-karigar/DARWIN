from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    ContentType,
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.chunking.code import CodeChunker


def create_code_document() -> tuple[ParsedDocument, str]:
    code = """
def calculate_total(price, quantity):
    subtotal = price * quantity
    return subtotal


def calculate_tax(total, rate):
    tax = total * rate
    return tax


def create_invoice(price, quantity, tax_rate):
    total = calculate_total(price, quantity)
    tax = calculate_tax(total, tax_rate)
    return total + tax
""".strip()

    document = ParsedDocument(
        document_id="code-document-1",
        title="billing.py",
        source_type=SourceType.CODE,
        source_uri="/code/billing.py",
        sections=(
            DocumentSection(
                section_id="code-section-1",
                text=code,
                heading_path=("billing.py",),
                start_offset=50,
                end_offset=50 + len(code),
            ),
        ),
        metadata={"language": "python"},
    )

    return document, code


def test_creates_bounded_code_chunks():
    document, _ = create_code_document()

    chunks = CodeChunker(
        RagSettings(
            child_chunk_tokens=35,
            child_chunk_overlap_tokens=5,
        )
    ).chunk(document)

    assert len(chunks) > 1
    assert all(chunk.token_count <= 35 for chunk in chunks)
    assert all(chunk.content_type == ContentType.CODE for chunk in chunks)
    assert all(chunk.parent_id == "code-section-1" for chunk in chunks)
    assert all(chunk.metadata["language"] == "python" for chunk in chunks)


def test_preserves_code_offsets():
    document, original_code = create_code_document()

    chunks = CodeChunker(
        RagSettings(
            child_chunk_tokens=35,
            child_chunk_overlap_tokens=5,
        )
    ).chunk(document)

    for chunk in chunks:
        relative_start = chunk.start_offset - 50
        relative_end = chunk.end_offset - 50

        assert original_code[relative_start:relative_end] == chunk.text


def test_ignores_non_code_documents():
    document = ParsedDocument(
        document_id="text-document",
        title="Notes",
        source_type=SourceType.TEXT,
        source_uri="/notes.txt",
        sections=(
            DocumentSection(
                section_id="section-1",
                text="Ordinary prose.",
            ),
        ),
    )

    assert CodeChunker().chunk(document) == ()
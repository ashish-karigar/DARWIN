from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    DocumentTable,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.chunking.tables import TableChunker


HEADER = (
    "| Item | Quantity | Price |\n"
    "|---|---:|---:|"
)


def create_document() -> ParsedDocument:
    rows = "\n".join(
        f"| Product {number} | {number} | ${number * 10}.00 |"
        for number in range(1, 11)
    )

    return ParsedDocument(
        document_id="document-1",
        title="Invoice",
        source_type=SourceType.PDF,
        source_uri="/documents/invoice.pdf",
        tables=(
            DocumentTable(
                table_id="table-1",
                markdown=f"{HEADER}\n{rows}",
                caption="Purchased items",
                page_number=2,
            ),
        ),
    )


def test_repeats_header_and_preserves_row_overlap():
    chunks = TableChunker(
        RagSettings(
            table_chunk_tokens=55,
            table_chunk_overlap_rows=1,
        )
    ).chunk(create_document())

    assert len(chunks) > 1

    for chunk in chunks:
        assert HEADER in chunk.text
        assert chunk.parent_id == "table-1"
        assert chunk.page_number == 2
        assert not chunk.metadata["oversized"]

    for previous, current in zip(chunks, chunks[1:]):
        assert previous.metadata["row_end"] == (
            current.metadata["row_start"]
        )


def test_drops_overlap_when_it_would_exceed_limit():
    chunks = TableChunker(
        RagSettings(
            table_chunk_tokens=35,
            table_chunk_overlap_rows=1,
        )
    ).chunk(create_document())

    assert all(chunk.token_count <= 35 for chunk in chunks)
    assert all(not chunk.metadata["oversized"] for chunk in chunks)
from app.ragv2.contracts import (
    DocumentTable,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.indexes.structured import (
    SQLiteStructuredIndex,
)


def make_document() -> ParsedDocument:
    return ParsedDocument(
        document_id="sales-document",
        title="Quarterly Sales",
        source_type=SourceType.PDF,
        source_uri="/sales.pdf",
        tables=(
            DocumentTable(
                table_id="sales-table",
                caption="Regional revenue",
                page_number=4,
                markdown=(
                    "| Region | Quarter | Revenue |\n"
                    "| --- | --- | ---: |\n"
                    "| East | Q1 | $1,200.50 |\n"
                    "| West | Q1 | $900.00 |\n"
                    "| East | Q2 | $1,500.00 |"
                ),
            ),
        ),
    )


def test_stores_searches_filters_and_aggregates_rows(tmp_path):
    index = SQLiteStructuredIndex(tmp_path / "structured.sqlite3")

    assert index.upsert(make_document()) == 3
    assert index.count() == 3
    assert index.search("east")[0].values["Region"] == "East"

    east_rows = index.filter_rows({"region": "East"})
    assert len(east_rows) == 2

    result = index.aggregate(
        "sum",
        column="Revenue",
        filters={"Region": "East"},
    )
    assert result.value == 2700.5
    assert result.matched_rows == 2


def test_reindex_and_delete_remove_stale_rows(tmp_path):
    index = SQLiteStructuredIndex(tmp_path / "structured.sqlite3")
    document = make_document()

    index.upsert(document)
    assert index.upsert(document) == 3
    assert index.count() == 3
    assert index.delete_document(document.document_id) == 3
    assert index.count() == 0

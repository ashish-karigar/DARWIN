from app.ragv2.contracts import (
    DocumentTable,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.indexes.document_store import SQLiteDocumentStore
from app.ragv2.ingest.indexes.structured import SQLiteStructuredIndex
from app.ragv2.retrieve.retrieval.structured import StructuredQueryEngine


class WordCounter:
    def count(self, text):
        return len(text.split())

    def truncate(self, text, maximum_tokens):
        return " ".join(text.split()[:maximum_tokens])


def make_document():
    return ParsedDocument(
        document_id="sales",
        title="Regional Sales",
        source_type=SourceType.MARKDOWN,
        source_uri="/sales.md",
        tables=(
            DocumentTable(
                table_id="revenue",
                caption="Regional revenue",
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


def test_executes_explicit_table_aggregation(tmp_path):
    structured = SQLiteStructuredIndex(tmp_path / "tables.sqlite3")
    documents = SQLiteDocumentStore(tmp_path / "documents.sqlite3")
    document = make_document()
    structured.upsert(document)
    documents.store(document)

    context = StructuredQueryEngine(
        structured_index=structured,
        document_store=documents,
        token_counter=WordCounter(),
    ).retrieve("What is the total Revenue for East?")

    assert context.has_direct_evidence is True
    assert "Result: 2700.5" in context.items[0].text
    assert "Column: Revenue" in context.items[0].text
    assert "Region = East" in context.items[0].text
    assert context.items[0].source_uri == "/sales.md"


def test_ignores_non_aggregation_questions(tmp_path):
    structured = SQLiteStructuredIndex(tmp_path / "tables.sqlite3")
    documents = SQLiteDocumentStore(tmp_path / "documents.sqlite3")
    document = make_document()
    structured.upsert(document)
    documents.store(document)

    context = StructuredQueryEngine(
        structured_index=structured,
        document_store=documents,
        token_counter=WordCounter(),
    ).retrieve("What does the report discuss?")

    assert context.items == ()
    assert context.has_direct_evidence is False


def test_abstains_when_two_tables_are_equally_plausible(tmp_path):
    structured = SQLiteStructuredIndex(tmp_path / "tables.sqlite3")
    documents = SQLiteDocumentStore(tmp_path / "documents.sqlite3")
    first = make_document()
    second = first.model_copy(
        update={
            "document_id": "sales-copy",
            "source_uri": "/sales-copy.md",
            "tables": (
                first.tables[0].model_copy(
                    update={"table_id": "revenue-copy"}
                ),
            ),
        }
    )
    structured.upsert(first)
    structured.upsert(second)
    documents.store(first)
    documents.store(second)

    context = StructuredQueryEngine(
        structured_index=structured,
        document_store=documents,
        token_counter=WordCounter(),
    ).retrieve("What is the total Revenue for East?")

    assert context.has_direct_evidence is False
    assert context.items == ()


def test_unknown_filter_does_not_aggregate_every_row(tmp_path):
    structured = SQLiteStructuredIndex(tmp_path / "tables.sqlite3")
    documents = SQLiteDocumentStore(tmp_path / "documents.sqlite3")
    document = make_document()
    structured.upsert(document)
    documents.store(document)

    context = StructuredQueryEngine(
        structured_index=structured,
        document_store=documents,
        token_counter=WordCounter(),
    ).retrieve("What is the total Revenue for North?")

    assert context.has_direct_evidence is False
    assert context.items == ()


def test_multiple_values_for_one_filter_are_not_guessed(tmp_path):
    structured = SQLiteStructuredIndex(tmp_path / "tables.sqlite3")
    documents = SQLiteDocumentStore(tmp_path / "documents.sqlite3")
    document = make_document()
    structured.upsert(document)
    documents.store(document)

    context = StructuredQueryEngine(
        structured_index=structured,
        document_store=documents,
        token_counter=WordCounter(),
    ).retrieve("What is the total Revenue for East and West?")

    assert context.has_direct_evidence is False
    assert context.items == ()

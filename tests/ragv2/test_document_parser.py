from types import SimpleNamespace

from docling_core.types.doc import (
    DocItemLabel,
    DoclingDocument,
    TableCell,
    TableData,
)

from app.ragv2.contracts import SourceType
from app.ragv2.ingest.parsers.document_parser import DocumentParser


class FakeConverter:
    def __init__(self, document: DoclingDocument):
        self.document = document

    def convert(self, **kwargs):
        return SimpleNamespace(document=self.document)


def create_docling_document() -> DoclingDocument:
    document = DoclingDocument(name="sample-report")

    document.add_title(text="DARWIN Report")
    document.add_heading(text="Retrieval", level=1)
    document.add_text(
        label=DocItemLabel.PARAGRAPH,
        text="Hybrid retrieval combines semantic and lexical search.",
    )

    document.add_table(
        data=TableData(
            num_rows=2,
            num_cols=2,
            table_cells=[
                TableCell(
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                    text="Method",
                    column_header=True,
                ),
                TableCell(
                    start_row_offset_idx=0,
                    end_row_offset_idx=1,
                    start_col_offset_idx=1,
                    end_col_offset_idx=2,
                    text="Score",
                    column_header=True,
                ),
                TableCell(
                    start_row_offset_idx=1,
                    end_row_offset_idx=2,
                    start_col_offset_idx=0,
                    end_col_offset_idx=1,
                    text="Dense",
                ),
                TableCell(
                    start_row_offset_idx=1,
                    end_row_offset_idx=2,
                    start_col_offset_idx=1,
                    end_col_offset_idx=2,
                    text="0.9",
                ),
            ],
        )
    )

    document.add_picture()
    return document


def test_supports_document_formats():
    parser = DocumentParser(converter=FakeConverter(create_docling_document()))

    assert parser.supports("report.pdf")
    assert parser.supports("report.docx")
    assert parser.supports("slides.pptx")
    assert parser.supports("table.xlsx")
    assert not parser.supports("notes.txt")


def test_converts_docling_output_to_contract(tmp_path):
    source = tmp_path / "report.pdf"
    source.write_bytes(b"fake PDF used by the injected converter")

    parser = DocumentParser(
        converter=FakeConverter(create_docling_document())
    )
    document = parser.parse(source)

    assert document.title == "DARWIN Report"
    assert document.source_type == SourceType.PDF

    assert len(document.sections) == 1
    assert document.sections[0].heading_path == (
        "DARWIN Report",
        "Retrieval",
    )

    assert len(document.tables) == 1
    assert "Dense" in document.tables[0].markdown

    assert len(document.images) == 1
    assert document.metadata["parser"] == "docling"
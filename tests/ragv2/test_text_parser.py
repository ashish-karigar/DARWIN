import pytest

from app.ragv2.contracts import SourceType
from app.ragv2.ingest.parsers.text_parser import TextParser


def test_supports_text_files():
    parser = TextParser()

    assert parser.supports("knowledge.txt")
    assert not parser.supports("document.pdf")
    assert not parser.supports("https://example.com/file.txt")


def test_parses_text_into_sections(tmp_path):
    source = tmp_path / "darwin_notes.txt"
    source.write_text(
        "DARWIN was created by Ashish.\n\n"
        "DARWIN uses an advanced RAG system.",
        encoding="utf-8",
    )

    document = TextParser().parse(source)

    assert document.title == "darwin notes"
    assert document.source_type == SourceType.TEXT
    assert len(document.sections) == 2
    assert document.sections[0].text == "DARWIN was created by Ashish."
    assert document.sections[1].start_offset > document.sections[0].end_offset
    assert document.metadata["parser"] == "text"


def test_document_ids_are_stable(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("Some useful information.", encoding="utf-8")

    parser = TextParser()

    first = parser.parse(source)
    second = parser.parse(source)

    assert first.document_id == second.document_id
    assert first.sections[0].section_id == second.sections[0].section_id


def test_rejects_empty_document(tmp_path):
    source = tmp_path / "empty.txt"
    source.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        TextParser().parse(source)
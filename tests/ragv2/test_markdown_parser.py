import pytest

from app.ragv2.contracts import SourceType
from app.ragv2.ingest.parsers.markdown_parser import MarkdownParser


def test_supports_markdown_files():
    parser = MarkdownParser()

    assert parser.supports("document.md")
    assert parser.supports("document.markdown")
    assert not parser.supports("document.txt")


def test_preserves_heading_hierarchy(tmp_path):
    source = tmp_path / "architecture.md"
    source.write_text(
        "# DARWIN\n\n"
        "Project overview.\n\n"
        "## Retrieval\n\n"
        "Retrieval explanation.\n\n"
        "### Reranking\n\n"
        "Reranking explanation.\n\n"
        "## Generation\n\n"
        "Generation explanation.",
        encoding="utf-8",
    )

    document = MarkdownParser().parse(source)

    assert document.title == "DARWIN"
    assert document.source_type == SourceType.MARKDOWN
    assert len(document.sections) == 4

    assert document.sections[0].heading_path == ("DARWIN",)
    assert document.sections[1].heading_path == ("DARWIN", "Retrieval")
    assert document.sections[2].heading_path == (
        "DARWIN",
        "Retrieval",
        "Reranking",
    )
    assert document.sections[3].heading_path == (
        "DARWIN",
        "Generation",
    )


def test_markdown_without_headings_becomes_one_section(tmp_path):
    source = tmp_path / "notes.md"
    source.write_text(
        "This document contains no headings.",
        encoding="utf-8",
    )

    document = MarkdownParser().parse(source)

    assert len(document.sections) == 1
    assert document.sections[0].heading_path == ()


def test_rejects_empty_markdown(tmp_path):
    source = tmp_path / "empty.md"
    source.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="empty"):
        MarkdownParser().parse(source)
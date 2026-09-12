import pytest

from app.ragv2.ingest.parsers.router import (
    ParserRouter,
    UnsupportedSourceError,
)


def test_registers_text_parser():
    router = ParserRouter()

    assert router.registered_parsers == ("text", "markdown", "web", "docling", "image", "code")


def test_selects_text_parser():
    router = ParserRouter()

    parser = router.select("notes.txt")

    assert parser.name == "text"


def test_rejects_unsupported_source():
    router = ParserRouter()

    with pytest.raises(UnsupportedSourceError):
        router.select("archive.zip")


def test_parses_using_selected_parser(tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("DARWIN knowledge.", encoding="utf-8")

    document = ParserRouter().parse(source)

    assert document.sections[0].text == "DARWIN knowledge."
    assert document.metadata["parser"] == "text"


def test_selects_markdown_parser():
    router = ParserRouter()

    parser = router.select("document.md")

    assert parser.name == "markdown"


def test_selects_web_parser():
    router = ParserRouter()

    parser = router.select("https://example.com/document")

    assert parser.name == "web"
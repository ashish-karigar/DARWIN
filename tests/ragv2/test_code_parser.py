from pathlib import Path

import pytest

from app.ragv2.contracts import SourceType
from app.ragv2.ingest.parsers.code_parser import CodeParser


def test_recognizes_supported_code_files():
    parser = CodeParser()

    assert parser.supports("service.py")
    assert parser.supports("frontend.tsx")
    assert parser.supports("query.sql")
    assert not parser.supports("notes.txt")
    assert not parser.supports("https://example.com/service.py")


def test_preserves_code_and_language_metadata(
    tmp_path: Path,
):
    source_code = (
        "def calculate_total(price: float, quantity: int):\n"
        "    return price * quantity\n"
    )

    path = tmp_path / "billing.py"
    path.write_text(source_code, encoding="utf-8")

    document = CodeParser().parse(path)
    section = document.sections[0]

    assert document.source_type == SourceType.CODE
    assert document.title == "billing.py"
    assert document.metadata["language"] == "python"
    assert section.text == source_code
    assert section.start_offset == 0
    assert section.end_offset == len(source_code)


def test_rejects_empty_code_file(tmp_path: Path):
    path = tmp_path / "empty.py"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError, match="Code file is empty"):
        CodeParser().parse(path)
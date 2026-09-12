import pytest

from app.ragv2.contracts import SourceType
from app.ragv2.ingest.parsers.router import UnsupportedSourceError
from app.ragv2.ingest.pipeline import IngestionPipeline


def test_pipeline_parses_and_validates_text(tmp_path):
    source = tmp_path / "knowledge.txt"
    source.write_text(
        "DARWIN uses a normalized document pipeline. " * 5,
        encoding="utf-8",
    )

    result = IngestionPipeline().parse(source)

    assert result.document.source_type == SourceType.TEXT
    assert result.document.metadata["parser"] == "text"
    assert result.final_quality.score == 1.0
    assert not result.used_assistance


def test_pipeline_rejects_unsupported_source(tmp_path):
    source = tmp_path / "archive.zip"
    source.write_bytes(b"unsupported content")

    with pytest.raises(UnsupportedSourceError):
        IngestionPipeline().parse(source)
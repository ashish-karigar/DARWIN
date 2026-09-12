from app.ragv2.contracts import (
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.parsers.document_cascade import (
    DocumentCascadeParser,
)


class FakeParser:
    def __init__(self, name: str, document: ParsedDocument):
        self.name = name
        self.document = document
        self.calls = 0

    def supports(self, source: object) -> bool:
        return True

    def parse(self, source: object) -> ParsedDocument:
        self.calls += 1
        return self.document


def create_document(
    text: str,
    parser_name: str,
) -> ParsedDocument:
    return ParsedDocument(
        document_id="document-1",
        title="Test Document",
        source_type=SourceType.PDF,
        source_uri="/tmp/test.pdf",
        sections=(
            DocumentSection(
                section_id=f"{parser_name}-section",
                text=text,
                page_number=1,
            ),
        ),
        metadata={
            "parser": parser_name,
            "page_count": 1,
        },
    )


def test_uses_only_liteparse_when_quality_is_good():
    fast = FakeParser(
        "liteparse",
        create_document("Reliable content. " * 20, "liteparse"),
    )
    quality = FakeParser(
        "docling",
        create_document("Alternative content. " * 20, "docling"),
    )

    parser = DocumentCascadeParser(
        fast_parser=fast,
        quality_parser=quality,
    )

    result = parser.parse("/tmp/test.pdf")

    assert result.metadata["parser"] == "liteparse"
    assert fast.calls == 1
    assert quality.calls == 0
    assert len(result.metadata["parse_attempts"]) == 1


def test_escalates_to_docling_when_liteparse_quality_is_poor():
    fast = FakeParser(
        "liteparse",
        create_document("Too little text.", "liteparse"),
    )
    quality = FakeParser(
        "docling",
        create_document("Reliable content. " * 20, "docling"),
    )

    parser = DocumentCascadeParser(
        fast_parser=fast,
        quality_parser=quality,
    )

    result = parser.parse("/tmp/test.pdf")

    assert result.metadata["parser"] == "docling"
    assert fast.calls == 1
    assert quality.calls == 1
    assert len(result.metadata["parse_attempts"]) == 2
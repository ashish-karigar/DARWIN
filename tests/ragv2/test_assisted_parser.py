from app.ragv2.config import RagSettings
from app.ragv2.contracts import (
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.parsers.assisted_parser import AssistedParser


SOURCE_URI = "/documents/report.pdf"


def create_document(
    text: str,
    page_count: int,
) -> ParsedDocument:
    return ParsedDocument(
        document_id="document-1",
        title="Report",
        source_type=SourceType.PDF,
        source_uri=SOURCE_URI,
        sections=(
            DocumentSection(
                section_id="section-1",
                text=text,
            ),
        ),
        metadata={"page_count": page_count},
    )


class FakeProvider:
    name = "fake-vision-parser"

    def __init__(self, document: ParsedDocument):
        self.document = document
        self.call_count = 0

    def parse(self, source):
        self.call_count += 1
        return self.document


def test_skips_assistance_for_good_parse():
    primary = create_document(
        "A complete and correctly extracted document section. " * 5,
        page_count=1,
    )
    provider = FakeProvider(primary)

    result = AssistedParser(
        provider=provider,
        rag_settings=RagSettings(enable_assisted_parsing=True),
    ).improve(SOURCE_URI, primary)

    assert not result.used_assistance
    assert provider.call_count == 0


def test_skips_assistance_when_disabled():
    primary = create_document("Very little text.", page_count=5)
    provider = FakeProvider(primary)

    result = AssistedParser(
        provider=provider,
        rag_settings=RagSettings(enable_assisted_parsing=False),
    ).improve(SOURCE_URI, primary)

    assert result.primary_quality.needs_assistance
    assert not result.used_assistance
    assert provider.call_count == 0


def test_uses_better_assisted_parse():
    primary = create_document("Very little text.", page_count=5)
    improved = create_document(
        "A complete document recovered by the assisted parser. " * 5,
        page_count=1,
    )
    provider = FakeProvider(improved)

    result = AssistedParser(
        provider=provider,
        rag_settings=RagSettings(enable_assisted_parsing=True),
    ).improve(SOURCE_URI, primary)

    assert result.used_assistance
    assert result.document == improved
    assert result.provider == "fake-vision-parser"
    assert provider.call_count == 1


def test_rejects_worse_assisted_parse():
    primary = create_document("Short text.", page_count=5)
    worse = create_document("Bad.", page_count=20)
    provider = FakeProvider(worse)

    result = AssistedParser(
        provider=provider,
        rag_settings=RagSettings(enable_assisted_parsing=True),
    ).improve(SOURCE_URI, primary)

    assert not result.used_assistance
    assert result.document == primary
from app.ragv2.contracts import (
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.validation import assess_parse_quality


def create_document(
    *section_texts: str,
    page_count: int = 0,
) -> ParsedDocument:
    sections = tuple(
        DocumentSection(
            section_id=f"section-{index}",
            text=text,
        )
        for index, text in enumerate(section_texts)
    )

    return ParsedDocument(
        document_id="document-1",
        title="Test Document",
        source_type=SourceType.PDF,
        source_uri="/documents/test.pdf",
        sections=sections,
        metadata={"page_count": page_count},
    )


def test_accepts_clean_document():
    document = create_document(
        "This is a complete and clearly extracted document section. " * 4
    )

    report = assess_parse_quality(document)

    assert report.score == 1.0
    assert not report.needs_assistance
    assert report.issues == ()


def test_flags_sparse_document():
    document = create_document(
        "Very little text.",
        page_count=5,
    )

    report = assess_parse_quality(document)

    assert report.needs_assistance
    assert any("sparse" in issue for issue in report.issues)


def test_flags_excessive_repetition():
    repeated = "This extracted paragraph was duplicated incorrectly. " * 2
    document = create_document(
        repeated,
        repeated,
        repeated,
        repeated,
    )

    report = assess_parse_quality(document)

    assert report.needs_assistance
    assert any("repetition" in issue for issue in report.issues)


def test_flags_corrupted_text():
    corrupted = ("Normal extracted document content. " * 8) + "���"
    document = create_document(corrupted)

    report = assess_parse_quality(document)

    assert report.needs_assistance
    assert any("corruption" in issue for issue in report.issues)
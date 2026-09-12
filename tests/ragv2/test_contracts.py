import pytest
from pydantic import ValidationError

from app.ragv2.contracts import (
    DocumentSection,
    ParsedDocument,
    SourceType,
)


def test_create_parsed_document():
    section = DocumentSection(
        section_id="section-1",
        text="DARWIN is an advanced assistant.",
        heading_path=("Introduction",),
        start_offset=0,
        end_offset=32,
    )

    document = ParsedDocument(
        document_id="document-1",
        title="DARWIN Overview",
        source_type=SourceType.TEXT,
        source_uri="data/knowledge.txt",
        sections=(section,),
    )

    assert document.sections[0].text == "DARWIN is an advanced assistant."
    assert document.tables == ()
    assert document.images == ()


def test_reject_empty_section():
    with pytest.raises(ValidationError):
        DocumentSection(
            section_id="section-1",
            text="",
        )


def test_reject_invalid_offsets():
    with pytest.raises(ValidationError):
        DocumentSection(
            section_id="section-1",
            text="Some text",
            start_offset=20,
            end_offset=10,
        )


def test_contract_is_immutable():
    section = DocumentSection(
        section_id="section-1",
        text="Some text",
    )

    with pytest.raises(ValidationError):
        section.text = "Changed"
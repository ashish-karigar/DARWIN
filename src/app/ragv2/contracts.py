from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

class SourceType(StrEnum):
    TEXT = "text"
    MARKDOWN = "markdown"
    WEB = "web"
    PDF = "pdf"
    DOCX = "docx"
    PPTX = "pptx"
    XLSX = "xlsx"
    IMAGE = "image"
    CODE = "code"

class ContentType(StrEnum):
    TEXT = "text"
    TABLE = "table"
    IMAGE_DESCRIPTION = "image_description"
    CODE = "code"

class QueryStrategy(StrEnum):
    DIRECT = "direct"
    CONVERSATION = "conversation"
    DECOMPOSE = "decompose"
    STEP_BACK = "step_back"

class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

class DocumentSection(Contract):
    section_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    heading_path: tuple[str, ...] = ()
    page_number: int | None = Field(default=None, ge=1)
    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_offset(self) -> "DocumentSection":
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("Both offsets must be provided together.")

        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("end_offset cannot precede start_offset.")

        return self

class DocumentTable(Contract):
    table_id: str = Field(min_length=1)
    markdown: str = Field(min_length=1)
    heading_path: tuple[str, ...] = ()
    caption: str | None = None
    page_number: int | None = Field(default=None, ge=1)

class DocumentImage(Contract):
    image_id: str = Field(min_length=1)
    heading_path: tuple[str, ...] = ()
    description: str | None = None
    caption: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    path_or_url: str | None = None

class ParsedDocument(Contract):
    document_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    source_type: SourceType
    source_uri: str = Field(min_length=1)
    authors: tuple[str, ...] = ()
    published_at: datetime | None = None
    parsed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sections: tuple[DocumentSection, ...] = ()
    tables: tuple[DocumentTable, ...] = ()
    images: tuple[DocumentImage, ...] = ()
    metadata: dict[str, Any] = {}

    @model_validator(mode="after")
    def validate_content(self) -> "ParsedDocument":
        if not self.sections and not self.tables and not self.images:
            raise ValueError(
                "A parsed document must contain a section, table, or image."
            )

        return self

class Chunk(Contract):
    chunk_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    parent_id: str = Field(min_length=1)

    text: str = Field(min_length=1)
    content_type: ContentType

    heading_path: tuple[str, ...] = ()
    page_number: int | None = Field(default=None, ge=1)
    source_uri: str = Field(min_length=1)

    start_offset: int | None = Field(default=None, ge=0)
    end_offset: int | None = Field(default=None, ge=0)
    token_count: int = Field(ge=1)

    metadata: dict[str, Any] = {}

    @model_validator(mode="after")
    def validate_offsets(self) -> "Chunk":
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValueError("Both chunk offsets must be provided together.")

        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("Chunk end_offset cannot precede start_offset.")

        return self

class RetrievalHit(Contract):
    chunk: Chunk
    score: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=1)
    retriever: str = Field(min_length=1)
    raw_score: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

class QueryAnalysis(Contract):
    original_query: str = Field(min_length=1)
    standalone_query: str = Field(min_length=1)
    strategy: QueryStrategy
    subqueries: tuple[str, ...] = ()
    step_back_query: str | None = None

    @model_validator(mode="after")
    def validate_strategy(self) -> "QueryAnalysis":
        if (
            self.strategy == QueryStrategy.DECOMPOSE
            and len(self.subqueries) < 2
        ):
            raise ValueError(
                "Decomposition requires at least two subqueries."
            )

        if (
            self.strategy == QueryStrategy.STEP_BACK
            and not self.step_back_query
        ):
            raise ValueError(
                "Step-back retrieval requires a broader query."
            )

        return self

    @property
    def retrieval_queries(self) -> tuple[str, ...]:
        if self.strategy == QueryStrategy.DECOMPOSE:
            return self.subqueries

        if self.strategy == QueryStrategy.STEP_BACK:
            return (
                self.standalone_query,
                self.step_back_query,
            )

        return (self.standalone_query,)

class EvidenceGrade(Contract):
    hit: RetrievalHit
    relevance_score: float = Field(ge=0.0, le=1.0)
    is_relevant: bool
    directly_answers: bool
    reason: str = Field(min_length=1)

class ContextItem(Contract):
    parent_id: str = Field(min_length=1)
    document_id: str = Field(min_length=1)
    document_title: str = Field(min_length=1)

    text: str = Field(min_length=1)
    content_type: ContentType

    source_uri: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    heading_path: tuple[str, ...] = ()

    supporting_chunk_ids: tuple[str, ...]
    relevance_score: float = Field(ge=0.0, le=1.0)
    directly_answers: bool
    expanded_from_parent: bool
    truncated: bool = False

class ContextBundle(Contract):
    query: str = Field(min_length=1)
    items: tuple[ContextItem, ...]
    total_tokens: int = Field(ge=0)
    has_direct_evidence: bool

class Citation(Contract):
    citation_id: str = Field(
        min_length=2,
        pattern=r"^S[1-9]\d*$",
    )
    document_id: str = Field(min_length=1)
    document_title: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    page_number: int | None = Field(default=None, ge=1)
    heading_path: tuple[str, ...] = ()
    parent_id: str = Field(min_length=1)
    supporting_chunk_ids: tuple[str, ...] = ()


class GroundedAnswer(Contract):
    query: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    citations: tuple[Citation, ...] = ()
    is_grounded: bool
    abstained: bool
    unsupported_claims: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_grounding(self) -> "GroundedAnswer":
        if self.abstained and self.is_grounded:
            raise ValueError(
                "An abstained answer cannot be grounded."
            )

        if self.is_grounded and not self.citations:
            raise ValueError(
                "A grounded answer requires citations."
            )

        return self
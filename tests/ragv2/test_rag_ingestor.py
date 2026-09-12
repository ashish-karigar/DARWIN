from app.ragv2.contracts import (
    Chunk,
    ContentType,
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.chunking.base import ChunkingResult
from app.ragv2.ingest.indexes.pipeline import IndexingResult
from app.ragv2.ingest.ingest import RagIngestor
from app.ragv2.ingest.parsers.assisted_parser import (
    AssistedParseResult,
)
from app.ragv2.ingest.validation import ParseQualityReport


class FakeParsingPipeline:
    def __init__(self, document, events):
        self.document = document
        self.events = events
        self.sources = []

    def parse(self, source):
        self.events.append("parse")
        self.sources.append(source)

        quality = ParseQualityReport(
            score=0.95,
            issues=(),
        )

        return AssistedParseResult(
            document=self.document,
            used_assistance=False,
            primary_quality=quality,
            final_quality=quality,
        )


class FakeChunkingPipeline:
    def __init__(self, chunks, events):
        self.chunks = chunks
        self.events = events

    def chunk(self, document):
        self.events.append("chunk")

        return ChunkingResult(
            document_id=document.document_id,
            chunks=self.chunks,
        )


class FakeIndexingPipeline:
    def __init__(self, events):
        self.events = events
        self.received_chunks = ()

    def index(self, document, chunks):
        self.events.append("index")
        self.received_chunks = tuple(chunks)

        return IndexingResult(
            document_id=document.document_id,
            chunk_count=len(chunks),
            token_count=sum(
                chunk.token_count for chunk in chunks
            ),
            replaced_vector_chunks=0,
            replaced_lexical_chunks=0,
        )


def create_document() -> ParsedDocument:
    return ParsedDocument(
        document_id="document-1",
        title="Production RAG",
        source_type=SourceType.TEXT,
        source_uri="/documents/rag.txt",
        sections=(
            DocumentSection(
                section_id="section-1",
                text="Hybrid retrieval improves recall.",
            ),
        ),
        metadata={"parser": "text"},
    )


def create_chunks() -> tuple[Chunk, ...]:
    return (
        Chunk(
            chunk_id="chunk-1",
            document_id="document-1",
            parent_id="section-1",
            text="Hybrid retrieval improves recall.",
            content_type=ContentType.TEXT,
            source_uri="/documents/rag.txt",
            token_count=6,
        ),
    )


def test_runs_complete_ingestion_flow():
    events = []
    document = create_document()
    chunks = create_chunks()

    parsing_pipeline = FakeParsingPipeline(
        document,
        events,
    )
    chunking_pipeline = FakeChunkingPipeline(
        chunks,
        events,
    )
    indexing_pipeline = FakeIndexingPipeline(events)

    ingestor = RagIngestor(
        parsing_pipeline=parsing_pipeline,
        chunking_pipeline=chunking_pipeline,
        indexing_pipeline=indexing_pipeline,
    )

    report = ingestor.ingest("/documents/rag.txt")

    assert events == ["parse", "chunk", "index"]
    assert indexing_pipeline.received_chunks == chunks

    assert report.document_id == "document-1"
    assert report.parser == "text"
    assert report.parse_quality == 0.95
    assert report.section_count == 1
    assert report.table_count == 0
    assert report.image_count == 0
    assert report.chunk_count == 1
    assert report.token_count == 6
    assert report.elapsed_seconds >= 0


def test_ingests_multiple_sources_in_order():
    events = []
    parsing_pipeline = FakeParsingPipeline(
        create_document(),
        events,
    )

    ingestor = RagIngestor(
        parsing_pipeline=parsing_pipeline,
        chunking_pipeline=FakeChunkingPipeline(
            create_chunks(),
            events,
        ),
        indexing_pipeline=FakeIndexingPipeline(events),
    )

    reports = ingestor.ingest_many(
        ("first.txt", "second.txt")
    )

    assert len(reports) == 2
    assert parsing_pipeline.sources == [
        "first.txt",
        "second.txt",
    ]
    assert events == [
        "parse",
        "chunk",
        "index",
        "parse",
        "chunk",
        "index",
    ]
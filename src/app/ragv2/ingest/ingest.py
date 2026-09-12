from collections.abc import Sequence
from dataclasses import dataclass
from time import perf_counter

from app.ragv2.ingest.chunking.pipeline import (
    ChunkingPipeline,
)
from app.ragv2.ingest.indexes.pipeline import (
    IndexingPipeline,
)
from app.ragv2.ingest.parsers.base import Source
from app.ragv2.ingest.pipeline import (
    IngestionPipeline as ParsingPipeline,
)


@dataclass(frozen=True, slots=True)
class IngestionReport:
    document_id: str
    title: str
    source_uri: str
    parser: str
    used_assistance: bool
    parse_quality: float
    section_count: int
    table_count: int
    image_count: int
    chunk_count: int
    token_count: int
    elapsed_seconds: float


class RagIngestor:
    """Runs a source through parsing, chunking, and indexing."""

    def __init__(
        self,
        parsing_pipeline: ParsingPipeline | None = None,
        chunking_pipeline: ChunkingPipeline | None = None,
        indexing_pipeline: IndexingPipeline | None = None,
    ):
        self.parsing_pipeline = (
            parsing_pipeline or ParsingPipeline()
        )
        self.chunking_pipeline = (
            chunking_pipeline or ChunkingPipeline()
        )
        self.indexing_pipeline = (
            indexing_pipeline or IndexingPipeline()
        )

    def ingest(self, source: Source) -> IngestionReport:
        started_at = perf_counter()

        parse_result = self.parsing_pipeline.parse(source)
        document = parse_result.document

        chunking_result = self.chunking_pipeline.chunk(document)

        indexing_result = self.indexing_pipeline.index(
            document,
            chunking_result.chunks,
        )

        return IngestionReport(
            document_id=document.document_id,
            title=document.title,
            source_uri=document.source_uri,
            parser=str(
                document.metadata.get("parser", "unknown")
            ),
            used_assistance=parse_result.used_assistance,
            parse_quality=parse_result.final_quality.score,
            section_count=len(document.sections),
            table_count=len(document.tables),
            image_count=len(document.images),
            chunk_count=indexing_result.chunk_count,
            token_count=indexing_result.token_count,
            elapsed_seconds=round(
                perf_counter() - started_at,
                3,
            ),
        )

    def ingest_many(
        self,
        sources: Sequence[Source],
    ) -> tuple[IngestionReport, ...]:
        return tuple(
            self.ingest(source)
            for source in sources
        )
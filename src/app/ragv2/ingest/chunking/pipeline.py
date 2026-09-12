from collections.abc import Iterable

from app.ragv2.contracts import Chunk, ParsedDocument
from app.ragv2.ingest.chunking.base import (
    Chunker,
    ChunkingResult,
)
from app.ragv2.ingest.chunking.prose import ProseChunker
from app.ragv2.ingest.chunking.tables import TableChunker
from app.ragv2.ingest.chunking.images import ImageChunker
from app.ragv2.ingest.chunking.code import CodeChunker


class ChunkingPipeline:
    """Runs every applicable chunker over a parsed document."""

    def __init__(
        self,
        chunkers: Iterable[Chunker] | None = None,
    ):
        self.chunkers = tuple(
            chunkers
            if chunkers is not None
            else (
                ProseChunker(),
                TableChunker(),
                ImageChunker(),
                CodeChunker(),
            )
        )

        if not self.chunkers:
            raise ValueError(
                "ChunkingPipeline requires at least one chunker."
            )

    def chunk(
        self,
        document: ParsedDocument,
    ) -> ChunkingResult:
        chunks: list[Chunk] = []

        for chunker in self.chunkers:
            chunks.extend(chunker.chunk(document))

        self._validate(document, chunks)

        return ChunkingResult(
            document_id=document.document_id,
            chunks=tuple(chunks),
        )

    @staticmethod
    def _validate(
        document: ParsedDocument,
        chunks: list[Chunk],
    ) -> None:
        chunk_ids = [chunk.chunk_id for chunk in chunks]

        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("Duplicate chunk IDs were generated.")

        if any(
            chunk.document_id != document.document_id
            for chunk in chunks
        ):
            raise ValueError(
                "A chunk references a different document."
            )
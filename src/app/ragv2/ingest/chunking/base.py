from dataclasses import dataclass
from typing import Protocol

from app.ragv2.contracts import Chunk, ParsedDocument

class Chunker(Protocol):
    name: str

    def chunk(
            self,
            document: ParsedDocument,
    ) -> tuple[Chunk, ...]:
        """Convert document content into searchable child chunks."""
        ...


@dataclass(frozen=True, slots=True)
class ChunkingResult:
    document_id: str
    chunks: tuple[Chunk, ...]

    @property
    def total_tokens(self) -> int:
        return sum(chunk.token_count for chunk in self.chunks)
from pathlib import Path
from typing import Protocol

from app.ragv2.contracts import ParsedDocument


Source = str | Path


class Parser(Protocol):
    name: str

    def supports(self, source: Source) -> bool:
        """Return whether this parser supports the supplied source."""
        ...

    def parse(self, source: Source) -> ParsedDocument:
        """Parse the source into DARWIN's normalized document format."""
        ...
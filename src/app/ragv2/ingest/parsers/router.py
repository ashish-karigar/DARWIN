from collections.abc import Iterable

from app.ragv2.contracts import ParsedDocument
from app.ragv2.ingest.parsers.base import Parser, Source
from app.ragv2.ingest.parsers.text_parser import TextParser
from app.ragv2.ingest.parsers.markdown_parser import MarkdownParser
from app.ragv2.ingest.parsers.web_parser import WebParser
from app.ragv2.ingest.parsers.document_parser import DocumentParser
from app.ragv2.ingest.parsers.image_parser import ImageParser
from app.ragv2.ingest.parsers.code_parser import CodeParser


class UnsupportedSourceError(ValueError):
    pass


class ParserRouter:
    def __init__(self, parsers: Iterable[Parser] | None = None):
        self._parsers = tuple(
            parsers if parsers is not None else (
                TextParser(),
                MarkdownParser(),
                WebParser(),
                DocumentParser(),
                ImageParser(),
                CodeParser(),
            )
        )

        if not self._parsers:
            raise ValueError("ParserRouter requires at least one parser.")

    @property
    def registered_parsers(self) -> tuple[str, ...]:
        return tuple(parser.name for parser in self._parsers)

    def select(self, source: Source) -> Parser:
        matches = [
            parser
            for parser in self._parsers
            if parser.supports(source)
        ]

        if not matches:
            raise UnsupportedSourceError(
                f"No parser supports source: {source}"
            )

        if len(matches) > 1:
            names = ", ".join(parser.name for parser in matches)
            raise RuntimeError(
                f"Multiple parsers support {source}: {names}"
            )

        return matches[0]

    def parse(self, source: Source) -> ParsedDocument:
        parser = self.select(source)
        return parser.parse(source)
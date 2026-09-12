from app.ragv2.config import RagSettings, settings
from app.ragv2.ingest.parsers.assisted_parser import (
    AssistedParseResult,
    AssistedParser,
)
from app.ragv2.ingest.parsers.base import Source
from app.ragv2.ingest.parsers.llamaparse_parser import (
    LlamaParseParser,
)
from app.ragv2.ingest.parsers.router import ParserRouter


class IngestionPipeline:
    def __init__(
        self,
        parser_router: ParserRouter | None = None,
        assisted_parser: AssistedParser | None = None,
        rag_settings: RagSettings = settings,
    ):
        self.parser_router = parser_router or ParserRouter()
        self.assisted_parser = assisted_parser or AssistedParser()

        if assisted_parser is not None:
            self.assisted_parser = assisted_parser
        else:
            provider = (
                LlamaParseParser(rag_settings=rag_settings)
                if rag_settings.enable_assisted_parsing
                else None
            )

            self.assisted_parser = AssistedParser(
                provider=provider,
                rag_settings=rag_settings,
            )

    def parse(self, source: Source) -> AssistedParseResult:
        parser = self.parser_router.select(source)

        try:
            primary_document = parser.parse(source)
        except Exception as error:
            if not self.assisted_parser.is_available_for(source):
                raise

            return self.assisted_parser.recover(
                source=source,
                error=error,
            )

        return self.assisted_parser.improve(
            source=source,
            primary_document=primary_document,
        )
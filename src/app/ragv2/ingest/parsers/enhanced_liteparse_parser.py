from liteparse import LiteParse

from app.ragv2.config import RagSettings, settings
from app.ragv2.ingest.parsers.liteparse_parser import (
    LiteParseParser,
)


class EnhancedLiteParseParser(LiteParseParser):
    """Heavier local LiteParse pass for structurally complex documents."""

    name = "liteparse_enhanced"

    def __init__(
        self,
        rag_settings: RagSettings = settings,
        parser: LiteParse | None = None,
    ):
        super().__init__(
            rag_settings=rag_settings,
            parser=parser,
        )

    @property
    def parser(self) -> LiteParse:
        if self._parser is None:
            self._parser = LiteParse(
                output_format="markdown",
                ocr_enabled=True,
                dpi=300,
                extract_blocks=True,
                extract_images=True,
                extract_screenshots=True,
                extract_vector_graphics=True,
                image_mode="placeholder",
                continue_on_page_error=True,
                quiet=True,
            )

        return self._parser
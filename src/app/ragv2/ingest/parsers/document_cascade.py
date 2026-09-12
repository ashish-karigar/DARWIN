from dataclasses import dataclass

from app.ragv2.contracts import ParsedDocument
from app.ragv2.ingest.parsers.base import Source
from app.ragv2.ingest.parsers.document_parser import DocumentParser
from app.ragv2.ingest.parsers.liteparse_parser import LiteParseParser
from app.ragv2.ingest.validation import (
    ParseQualityReport,
    assess_parse_quality,
)


@dataclass(frozen=True, slots=True)
class LocalParseAttempt:
    parser: str
    quality: ParseQualityReport


class DocumentCascadeParser:
    """Uses LiteParse first and escalates difficult documents to Docling."""

    name = "document_cascade"

    def __init__(
        self,
        fast_parser: LiteParseParser | None = None,
        quality_parser: DocumentParser | None = None,
    ):
        self.fast_parser = fast_parser or LiteParseParser()
        self.quality_parser = quality_parser or DocumentParser()

    def supports(self, source: Source) -> bool:
        return self.fast_parser.supports(source)

    def parse(self, source: Source) -> ParsedDocument:
        attempts: list[LocalParseAttempt] = []

        try:
            fast_document = self.fast_parser.parse(source)
            fast_quality = assess_parse_quality(fast_document)
        except Exception as error:
            attempts.append(
                LocalParseAttempt(
                    parser=self.fast_parser.name,
                    quality=ParseQualityReport(
                        score=0.0,
                        issues=(
                            f"Parsing failed: "
                            f"{type(error).__name__}: {error}",
                        ),
                    ),
                )
            )

            return self._parse_with_docling(source, attempts)

        attempts.append(
            LocalParseAttempt(
                parser=self.fast_parser.name,
                quality=fast_quality,
            )
        )

        if not fast_quality.needs_assistance:
            return self._with_attempts(fast_document, attempts)

        return self._parse_with_docling(
            source,
            attempts,
            fallback_document=fast_document,
        )

    @staticmethod
    def _with_attempts(
        document: ParsedDocument,
        attempts: list[LocalParseAttempt],
    ) -> ParsedDocument:
        metadata = {
            **document.metadata,
            "parse_attempts": [
                {
                    "parser": attempt.parser,
                    "quality_score": attempt.quality.score,
                    "issues": list(attempt.quality.issues),
                }
                for attempt in attempts
            ],
        }

        return document.model_copy(
            update={"metadata": metadata},
        )

    def _parse_with_docling(
            self,
            source: Source,
            attempts: list[LocalParseAttempt],
            fallback_document: ParsedDocument | None = None,
    ) -> ParsedDocument:
        quality_document = self.quality_parser.parse(source)
        quality_report = assess_parse_quality(quality_document)

        attempts.append(
            LocalParseAttempt(
                parser=self.quality_parser.name,
                quality=quality_report,
            )
        )

        if fallback_document is None:
            selected_document = quality_document
        else:
            fallback_quality = assess_parse_quality(fallback_document)
            selected_document = (
                quality_document
                if quality_report.score > fallback_quality.score
                else fallback_document
            )

        return self._with_attempts(selected_document, attempts)
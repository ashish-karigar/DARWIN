from dataclasses import dataclass
from typing import Protocol

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import ParsedDocument
from app.ragv2.ingest.parsers.base import Source
from app.ragv2.ingest.validation import (
    ParseQualityReport,
    assess_parse_quality,
)


class AssistedParsingProvider(Protocol):
    name: str

    def parse(self, source: Source) -> ParsedDocument:
        """Parse a difficult source using an LLM or vision service."""
        ...


@dataclass(frozen=True, slots=True)
class AssistedParseResult:
    document: ParsedDocument
    used_assistance: bool
    primary_quality: ParseQualityReport
    final_quality: ParseQualityReport
    provider: str | None = None


class AssistedParser:
    def __init__(
        self,
        provider: AssistedParsingProvider | None = None,
        rag_settings: RagSettings = settings,
    ):
        self.provider = provider
        self.settings = rag_settings

    def improve(
        self,
        source: Source,
        primary_document: ParsedDocument,
    ) -> AssistedParseResult:
        primary_quality = assess_parse_quality(primary_document)

        if not primary_quality.needs_assistance:
            return AssistedParseResult(
                document=primary_document,
                used_assistance=False,
                primary_quality=primary_quality,
                final_quality=primary_quality,
            )

        if not self.settings.enable_assisted_parsing:
            return AssistedParseResult(
                document=primary_document,
                used_assistance=False,
                primary_quality=primary_quality,
                final_quality=primary_quality,
            )

        if self.provider is None:
            raise RuntimeError(
                "Assisted parsing is enabled, but no provider is configured."
            )

        assisted_document = self.provider.parse(source)

        if assisted_document.source_uri != primary_document.source_uri:
            raise ValueError(
                "Assisted parser returned a different source URI."
            )

        assisted_quality = assess_parse_quality(assisted_document)

        if assisted_quality.score <= primary_quality.score:
            return AssistedParseResult(
                document=primary_document,
                used_assistance=False,
                primary_quality=primary_quality,
                final_quality=primary_quality,
                provider=self.provider.name,
            )

        return AssistedParseResult(
            document=assisted_document,
            used_assistance=True,
            primary_quality=primary_quality,
            final_quality=assisted_quality,
            provider=self.provider.name,
        )

    def is_available_for(self, source: Source) -> bool:
        if not self.settings.enable_assisted_parsing:
            return False

        if self.provider is None:
            return False

        supports = getattr(self.provider, "supports", None)
        return supports(source) if supports is not None else True

    def recover(
            self,
            source: Source,
            error: Exception,
    ) -> AssistedParseResult:
        if not self.is_available_for(source):
            raise RuntimeError(
                "No assisted parser is available for recovery."
            ) from error

        assisted_document = self.provider.parse(source)
        assisted_quality = assess_parse_quality(assisted_document)

        failed_quality = ParseQualityReport(
            score=0.0,
            issues=(
                f"Local parsing failed: "
                f"{type(error).__name__}: {error}",
            ),
        )

        return AssistedParseResult(
            document=assisted_document,
            used_assistance=True,
            primary_quality=failed_quality,
            final_quality=assisted_quality,
            provider=self.provider.name,
        )
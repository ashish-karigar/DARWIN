import re
from hashlib import sha256
from pathlib import Path

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    DocumentSection,
    ParsedDocument,
    SourceType
)
from app.ragv2.ingest.parsers.base import Source

class TextParser:
    name = "text"
    supported_extensions = frozenset({".txt"})

    def __init__(self, rag_settings: RagSettings = settings):
        self.settings = rag_settings

    def supports(self, source: Source) -> bool:
        source_text = str(source)

        if source_text.startswith(("http://", "https://")):
            return False

        return Path(source).suffix.lower() in self.supported_extensions

    def parse(self, source: Source) -> ParsedDocument:
        path = Path(source).expanduser().resolve()

        if not path.is_file():
            raise FileNotFoundError(f"{path} is not a file")

        max_bytes = self.settings.maximum_file_size_mb * 1024 * 1024
        if path.stat().st_size > max_bytes:
            raise ValueError(f"Document exceeds {self.settings.maximum_file_size_mb} MB")

        text = path.read_text(
            encoding=self.settings.default_encoding
        ).strip()

        if not text:
            raise ValueError(f"Text document is empty: {path}")

        source_uri = str(path)
        document_id = sha256(source_uri.encode("utf-8")).hexdigest()

        sections = self._create_sections(text, document_id)

        return ParsedDocument(
            document_id=document_id,
            title=path.stem.replace("_", " ").strip(),
            source_type=SourceType.TEXT,
            source_uri=source_uri,
            sections=tuple(sections),
            metadata={
                "parser": self.name,
                "parser_version": "1.0",
                "file_size_bytes": path.stat().st_size,
            },
        )

    @staticmethod
    def _create_sections(
            text: str, document_id: str
    ) -> list[DocumentSection]:
        sections = []
        cursor = 0

        for index, raw_section in enumerate(
            re.split(r"\n\s*\n+", text)
        ):
            content = raw_section.strip()
            if not content:
                continue

            start_offset = text.find(content, cursor)
            end_offset = start_offset + len(content)
            cursor = end_offset

            section_id = sha256(
                f"{document_id}:{index}:{content}".encode("utf-8")
            ).hexdigest()

            sections.append(
                DocumentSection(
                    section_id=section_id,
                    text=content,
                    start_offset=start_offset,
                    end_offset=end_offset,
                )
            )

        return sections
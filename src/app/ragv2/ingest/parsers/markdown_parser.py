import re
from hashlib import sha256
from pathlib import Path

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.parsers.base import Source


HEADING_PATTERN = re.compile(
    r"^(#{1,6})\s+(.+?)\s*$",
    re.MULTILINE,
)


class MarkdownParser:
    name = "markdown"
    supported_extensions = frozenset({".md", ".markdown"})

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
            raise FileNotFoundError(f"Markdown document not found: {path}")

        maximum_bytes = self.settings.maximum_file_size_mb * 1024 * 1024
        if path.stat().st_size > maximum_bytes:
            raise ValueError(
                f"Document exceeds {self.settings.maximum_file_size_mb} MB."
            )

        text = path.read_text(
            encoding=self.settings.default_encoding
        ).strip()

        if not text:
            raise ValueError(f"Markdown document is empty: {path}")

        source_uri = str(path)
        document_id = sha256(source_uri.encode("utf-8")).hexdigest()
        sections = self._create_sections(text, document_id)

        first_heading = HEADING_PATTERN.search(text)
        title = (
            first_heading.group(2).strip()
            if first_heading and len(first_heading.group(1)) == 1
            else path.stem.replace("_", " ").strip()
        )

        return ParsedDocument(
            document_id=document_id,
            title=title,
            source_type=SourceType.MARKDOWN,
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
        text: str,
        document_id: str,
    ) -> list[DocumentSection]:
        headings = list(HEADING_PATTERN.finditer(text))
        sections: list[DocumentSection] = []
        heading_path: list[str] = []

        if not headings:
            return [
                MarkdownParser._section(
                    document_id=document_id,
                    index=0,
                    text=text,
                    heading_path=(),
                    start_offset=0,
                    end_offset=len(text),
                )
            ]

        introduction = text[:headings[0].start()].strip()
        if introduction:
            start = text.find(introduction)
            sections.append(
                MarkdownParser._section(
                    document_id=document_id,
                    index=len(sections),
                    text=introduction,
                    heading_path=(),
                    start_offset=start,
                    end_offset=start + len(introduction),
                )
            )

        for position, heading in enumerate(headings):
            level = len(heading.group(1))
            title = heading.group(2).strip()

            heading_path = heading_path[: level - 1]
            heading_path.append(title)

            content_start = heading.end()
            content_end = (
                headings[position + 1].start()
                if position + 1 < len(headings)
                else len(text)
            )

            content = text[content_start:content_end].strip()

            if content:
                start_offset = text.find(content, content_start)
                end_offset = start_offset + len(content)
            else:
                content = title
                start_offset = heading.start()
                end_offset = heading.end()

            sections.append(
                MarkdownParser._section(
                    document_id=document_id,
                    index=len(sections),
                    text=content,
                    heading_path=tuple(heading_path),
                    start_offset=start_offset,
                    end_offset=end_offset,
                )
            )

        return sections

    @staticmethod
    def _section(
        document_id: str,
        index: int,
        text: str,
        heading_path: tuple[str, ...],
        start_offset: int,
        end_offset: int,
    ) -> DocumentSection:
        section_id = sha256(
            f"{document_id}:{index}:{heading_path}:{text}".encode("utf-8")
        ).hexdigest()

        return DocumentSection(
            section_id=section_id,
            text=text,
            heading_path=heading_path,
            start_offset=start_offset,
            end_offset=end_offset,
        )
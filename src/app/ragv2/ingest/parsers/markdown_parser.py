import re
from hashlib import sha256
from pathlib import Path

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    DocumentSection,
    DocumentTable,
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
        tables, prose_text = self._extract_tables(text, document_id)
        sections = self._create_sections(prose_text, document_id)

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
            tables=tuple(tables),
            metadata={
                "parser": self.name,
                "parser_version": "1.0",
                "file_size_bytes": path.stat().st_size,
            },
        )

    @classmethod
    def _extract_tables(
        cls,
        text: str,
        document_id: str,
    ) -> tuple[list[DocumentTable], str]:
        """Extracts pipe tables while preserving prose character offsets."""

        lines = text.splitlines(keepends=True)
        offsets = []
        cursor = 0

        for line in lines:
            offsets.append(cursor)
            cursor += len(line)

        tables = []
        spans = []
        in_fence = False
        index = 0

        while index < len(lines):
            stripped = lines[index].strip()

            if stripped.startswith(("```", "~~~")):
                in_fence = not in_fence
                index += 1
                continue

            if (
                in_fence
                or index + 1 >= len(lines)
                or "|" not in stripped
                or not cls._is_table_separator(lines[index + 1])
            ):
                index += 1
                continue

            end_index = index + 2

            while end_index < len(lines):
                row = lines[end_index].strip()

                if not row or "|" not in row:
                    break

                if row.startswith(("```", "~~~", "#")):
                    break

                end_index += 1

            markdown = "".join(
                lines[index:end_index]
            ).strip()
            start_offset = offsets[index]
            end_offset = (
                offsets[end_index]
                if end_index < len(offsets)
                else len(text)
            )
            table_index = len(tables)
            table_id = sha256(
                (
                    f"{document_id}:table:{table_index}:"
                    f"{markdown}"
                ).encode("utf-8")
            ).hexdigest()
            tables.append(
                DocumentTable(
                    table_id=table_id,
                    markdown=markdown,
                    heading_path=cls._heading_path_at(
                        text,
                        start_offset,
                    ),
                )
            )
            spans.append((start_offset, end_offset))
            index = end_index

        prose_text = text

        for start_offset, end_offset in reversed(spans):
            replacement = re.sub(
                r"[^\n]",
                " ",
                prose_text[start_offset:end_offset],
            )
            prose_text = (
                prose_text[:start_offset]
                + replacement
                + prose_text[end_offset:]
            )

        return tables, prose_text

    @staticmethod
    def _is_table_separator(line: str) -> bool:
        cells = [
            cell.strip()
            for cell in line.strip().strip("|").split("|")
        ]
        return bool(cells) and all(
            re.fullmatch(r":?-{3,}:?", cell)
            for cell in cells
        )

    @staticmethod
    def _heading_path_at(
        text: str,
        offset: int,
    ) -> tuple[str, ...]:
        path = []

        for heading in HEADING_PATTERN.finditer(
            text,
            0,
            offset,
        ):
            level = len(heading.group(1))
            path = path[:level - 1]
            path.append(heading.group(2).strip())

        return tuple(path)

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

from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

from liteparse import LiteParse

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    DocumentSection,
    ParsedDocument,
    SourceType,
    DocumentImage,
    DocumentTable,
)
from app.ragv2.ingest.parsers.base import Source


SOURCE_TYPES = {
    ".pdf": SourceType.PDF,
    ".docx": SourceType.DOCX,
    ".pptx": SourceType.PPTX,
    ".xlsx": SourceType.XLSX,
}

SUPPORTED_EXTENSIONS = frozenset(SOURCE_TYPES)


class LiteParseParser:
    """Fast, local parser for layout-aware document extraction."""

    name = "liteparse"

    def __init__(
        self,
        rag_settings: RagSettings = settings,
        parser: LiteParse | None = None,
    ):
        self.settings = rag_settings
        self._parser = parser

    @property
    def parser(self) -> LiteParse:
        if self._parser is None:
            self._parser = LiteParse(
                output_format="markdown",
                ocr_enabled=True,
                extract_blocks=True,
                image_mode="placeholder",
                quiet=True,
            )

        return self._parser

    def supports(self, source: Source) -> bool:
        source_text = str(source)

        if source_text.startswith(("http://", "https://")):
            return False

        return Path(source).suffix.lower() in SUPPORTED_EXTENSIONS

    def parse(self, source: Source) -> ParsedDocument:
        path = Path(source).expanduser().resolve()
        self._validate(path)

        complexity_pages = self.parser.is_complex(path)

        complexity_reasons = sorted({
            reason
            for page in complexity_pages
            if page.needs_ocr
            for reason in page.reasons
        })

        result = self.parser.parse(path)
        document_id = sha256(str(path).encode("utf-8")).hexdigest()

        sections = []
        tables = []
        images = []
        heading_path: list[str] = []
        title = path.stem

        for page in result.pages:
            blocks = page.blocks or []

            for block_index, block in enumerate(blocks):
                text = (block.text or "").strip()

                if block.kind == "heading" and text:
                    level = max(1, block.level or 1)
                    heading_path = heading_path[: level - 1]
                    heading_path.append(text)

                    if level == 1 and title == path.stem:
                        title = text

                    continue

                if block.kind == "table":
                    markdown = self._table_to_markdown(
                        block.header or [],
                        block.rows or [],
                    )

                    if markdown:
                        tables.append(
                            DocumentTable(
                                table_id=self._stable_id(
                                    document_id,
                                    page.page_num,
                                    block_index,
                                    markdown,
                                ),
                                markdown=markdown,
                                heading_path=tuple(heading_path),
                                page_number=page.page_num,
                            )
                        )

                    continue

                if block.kind == "figure":
                    images.append(
                        DocumentImage(
                            image_id=self._stable_id(
                                document_id,
                                page.page_num,
                                block_index,
                                "figure",
                            ),
                            heading_path=tuple(heading_path),
                            caption=text or None,
                            page_number=page.page_num,
                        )
                    )

                    continue

                if not text:
                    continue

                sections.append(
                    DocumentSection(
                        section_id=self._stable_id(
                            document_id,
                            page.page_num,
                            block_index,
                            text,
                        ),
                        text=text,
                        heading_path=tuple(heading_path),
                        page_number=page.page_num,
                    )
                )

        if not sections and not tables and not images:
            fallback = result.text.strip()
            if not fallback:
                raise ValueError(f"No useful content extracted from: {path}")

            sections.append(
                DocumentSection(
                    section_id=self._stable_id(
                        document_id,
                        1,
                        0,
                        fallback,
                    ),
                    text=fallback,
                )
            )

        return ParsedDocument(
            document_id=document_id,
            title=title,
            source_type=SOURCE_TYPES[path.suffix.lower()],
            source_uri=str(path),
            sections=tuple(sections),
            metadata={
                "parser": self.name,
                "parser_version": version("liteparse"),
                "file_size_bytes": path.stat().st_size,
                "page_count": result.num_pages,
                "complex_page_count": sum(
                    page.needs_ocr for page in complexity_pages
                ),
                "complexity_reasons": complexity_reasons,
                "extracted_image_count": len(
                    getattr(result, "images", None) or []
                ),
                "screenshot_count": len(
                    getattr(result, "screenshots", None) or []
                ),
                "vector_graphics_page_count": sum(
                    bool(getattr(page, "vector_graphics", None))
                    for page in result.pages
                ),
            },
            tables=tuple(tables),
            images=tuple(images),
        )

    def _validate(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"Document not found: {path}")

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported document type: {path.suffix}")

        maximum_bytes = self.settings.maximum_file_size_mb * 1024 * 1024

        if path.stat().st_size > maximum_bytes:
            raise ValueError(
                f"Document exceeds {self.settings.maximum_file_size_mb} MB."
            )

    @staticmethod
    def _stable_id(
        document_id: str,
        page_number: int,
        block_index: int,
        text: str,
    ) -> str:
        identity = (
            f"{document_id}:{page_number}:{block_index}:{text}"
        )
        return sha256(identity.encode("utf-8")).hexdigest()

    @staticmethod
    def _table_to_markdown(
            header: list[object],
            rows: list[list[object]],
    ) -> str:
        def cell_text(cell: object) -> str:
            return (
                str(getattr(cell, "text", ""))
                .strip()
                .replace("\n", " ")
                .replace("|", "\\|")
            )

        width = max(
            [len(header), *(len(row) for row in rows)],
            default=0,
        )

        if width == 0:
            return ""

        header_cells = [cell_text(cell) for cell in header]
        header_cells.extend([""] * (width - len(header_cells)))

        rendered_rows = []

        for row in rows:
            cells = [cell_text(cell) for cell in row]
            cells.extend([""] * (width - len(cells)))
            rendered_rows.append(f"| {' | '.join(cells)} |")

        return "\n".join([
            f"| {' | '.join(header_cells)} |",
            f"| {' | '.join(['---'] * width)} |",
            *rendered_rows,
        ])
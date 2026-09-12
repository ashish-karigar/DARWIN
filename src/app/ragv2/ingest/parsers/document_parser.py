from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

from docling.document_converter import DocumentConverter
from docling_core.types.doc import (
    DocItemLabel,
    DoclingDocument,
    PictureItem,
    TableItem,
    TextItem,
)

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    DocumentImage,
    DocumentSection,
    DocumentTable,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.parsers.base import Source


SOURCE_TYPES = {
    ".pdf": SourceType.PDF,
    ".docx": SourceType.DOCX,
    ".pptx": SourceType.PPTX,
    ".xlsx": SourceType.XLSX,
}


class DocumentParser:
    name = "docling"
    supported_extensions = frozenset(SOURCE_TYPES)

    def __init__(
        self,
        rag_settings: RagSettings = settings,
        converter: DocumentConverter | None = None,
    ):
        self.settings = rag_settings
        self._converter = converter

    @property
    def converter(self) -> DocumentConverter:
        if self._converter is None:
            self._converter = DocumentConverter()

        return self._converter

    def supports(self, source: Source) -> bool:
        source_text = str(source)

        if source_text.startswith(("http://", "https://")):
            return False

        return Path(source).suffix.lower() in self.supported_extensions

    def parse(self, source: Source) -> ParsedDocument:
        path = Path(source).expanduser().resolve()

        if not path.is_file():
            raise FileNotFoundError(f"Document not found: {path}")

        source_type = SOURCE_TYPES.get(path.suffix.lower())
        if source_type is None:
            raise ValueError(f"Unsupported document type: {path.suffix}")

        maximum_bytes = self.settings.maximum_file_size_mb * 1024 * 1024
        if path.stat().st_size > maximum_bytes:
            raise ValueError(
                f"Document exceeds {self.settings.maximum_file_size_mb} MB."
            )

        result = self.converter.convert(
            source=path,
            max_file_size=maximum_bytes,
        )

        document_id = sha256(
            str(path).encode("utf-8")
        ).hexdigest()

        sections, tables, images = self._extract_elements(
            result.document,
            document_id,
        )

        if not sections:
            fallback = result.document.export_to_markdown().strip()
            if not fallback:
                raise ValueError(f"No useful content extracted from: {path}")

            sections.append(
                DocumentSection(
                    section_id=self._stable_id(
                        document_id,
                        "fallback",
                        fallback,
                    ),
                    text=fallback,
                )
            )

        return ParsedDocument(
            document_id=document_id,
            title=self._document_title(result.document, path.stem),
            source_type=source_type,
            source_uri=str(path),
            sections=tuple(sections),
            tables=tuple(tables),
            images=tuple(images),
            metadata={
                "parser": self.name,
                "parser_version": version("docling"),
                "file_size_bytes": path.stat().st_size,
                "page_count": len(result.document.pages),
            },
        )

    def _extract_elements(
        self,
        document: DoclingDocument,
        document_id: str,
    ) -> tuple[
        list[DocumentSection],
        list[DocumentTable],
        list[DocumentImage],
    ]:
        sections: list[DocumentSection] = []
        tables: list[DocumentTable] = []
        images: list[DocumentImage] = []

        heading_path: list[str] = []
        title_depth = 0

        for item, _ in document.iterate_items():
            page_number = self._page_number(item)

            if isinstance(item, TextItem):
                text = item.text.strip()
                if not text:
                    continue

                if item.label == DocItemLabel.TITLE:
                    heading_path = [text]
                    title_depth = 1
                    continue

                if item.label == DocItemLabel.SECTION_HEADER:
                    level = max(1, getattr(item, "level", 1))
                    parent_depth = title_depth + level - 1
                    heading_path = heading_path[:parent_depth]
                    heading_path.append(text)
                    continue

                if item.label in {
                    DocItemLabel.PAGE_HEADER,
                    DocItemLabel.PAGE_FOOTER,
                }:
                    continue

                sections.append(
                    DocumentSection(
                        section_id=self._stable_id(
                            document_id,
                            "section",
                            item.self_ref,
                        ),
                        text=text,
                        heading_path=tuple(heading_path),
                        page_number=page_number,
                    )
                )

            elif isinstance(item, TableItem):
                markdown = item.export_to_markdown(document).strip()
                if not markdown:
                    continue

                caption = item.caption_text(document).strip() or None

                tables.append(
                    DocumentTable(
                        table_id=self._stable_id(
                            document_id,
                            "table",
                            item.self_ref,
                        ),
                        markdown=markdown,
                        heading_path=tuple(heading_path),
                        caption=caption,
                        page_number=page_number,
                    )
                )

            elif isinstance(item, PictureItem):
                caption = item.caption_text(document).strip() or None

                images.append(
                    DocumentImage(
                        image_id=self._stable_id(
                            document_id,
                            "image",
                            item.self_ref,
                        ),
                        heading_path=tuple(heading_path),
                        caption=caption,
                        page_number=page_number,
                    )
                )

        return sections, tables, images

    @staticmethod
    def _page_number(item: object) -> int | None:
        provenance = getattr(item, "prov", None)
        return provenance[0].page_no if provenance else None

    @staticmethod
    def _stable_id(
        document_id: str,
        element_type: str,
        value: object,
    ) -> str:
        identity = f"{document_id}:{element_type}:{value}"
        return sha256(identity.encode("utf-8")).hexdigest()

    @staticmethod
    def _document_title(
            document: DoclingDocument,
            fallback: str,
    ) -> str:
        for item, _ in document.iterate_items():
            if (
                    isinstance(item, TextItem)
                    and item.label == DocItemLabel.TITLE
                    and item.text.strip()
            ):
                return item.text.strip()

        return document.name or fallback
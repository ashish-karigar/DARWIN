from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

from liteparse import LiteParse

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    DocumentImage,
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.parsers.base import Source


SUPPORTED_EXTENSIONS = frozenset({
    ".png",
    ".jpg",
    ".jpeg",
    ".tiff",
    ".tif",
    ".bmp",
    ".webp",
})


class ImageParser:
    """Extracts text from standalone images using local OCR."""

    name = "image"

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
                output_format="text",
                ocr_enabled=True,
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

        result = self.parser.parse(path)
        document_id = sha256(str(path).encode("utf-8")).hexdigest()
        extracted_text = result.text.strip()

        sections = ()

        if extracted_text:
            sections = (
                DocumentSection(
                    section_id=self._stable_id(
                        document_id,
                        "ocr",
                        extracted_text,
                    ),
                    text=extracted_text,
                    page_number=1,
                ),
            )

        image = DocumentImage(
            image_id=self._stable_id(
                document_id,
                "image",
                path.name,
            ),
            page_number=1,
            path_or_url=str(path),
        )

        return ParsedDocument(
            document_id=document_id,
            title=path.stem,
            source_type=SourceType.IMAGE,
            source_uri=str(path),
            sections=sections,
            images=(image,),
            metadata={
                "parser": self.name,
                "parser_version": version("liteparse"),
                "file_size_bytes": path.stat().st_size,
                "page_count": 1,
                "ocr_text_found": bool(extracted_text),
            },
        )

    def _validate(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {path}")

        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported image type: {path.suffix}")

        maximum_bytes = self.settings.maximum_file_size_mb * 1024 * 1024

        if path.stat().st_size > maximum_bytes:
            raise ValueError(
                f"Image exceeds {self.settings.maximum_file_size_mb} MB."
            )

    @staticmethod
    def _stable_id(
        document_id: str,
        element_type: str,
        value: str,
    ) -> str:
        identity = f"{document_id}:{element_type}:{value}"
        return sha256(identity.encode("utf-8")).hexdigest()
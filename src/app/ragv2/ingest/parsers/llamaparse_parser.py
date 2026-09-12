import os
import re
from hashlib import sha256
from importlib.metadata import version
from pathlib import Path

from llama_cloud import LlamaCloud

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    DocumentImage,
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.parsers.base import Source


SOURCE_TYPES = {
    ".pdf": SourceType.PDF,
    ".docx": SourceType.DOCX,
    ".pptx": SourceType.PPTX,
    ".xlsx": SourceType.XLSX,
    ".png": SourceType.IMAGE,
    ".jpg": SourceType.IMAGE,
    ".jpeg": SourceType.IMAGE,
    ".tiff": SourceType.IMAGE,
    ".tif": SourceType.IMAGE,
    ".bmp": SourceType.IMAGE,
    ".webp": SourceType.IMAGE,
}


class LlamaParseParser:
    """Cloud fallback for documents that local parsers cannot parse well."""

    name = "llamaparse"

    def __init__(
        self,
        rag_settings: RagSettings = settings,
        client: LlamaCloud | None = None,
        tier: str = "agentic",
    ):
        self.settings = rag_settings
        self._client = client
        self.tier = tier

    @property
    def client(self) -> LlamaCloud:
        if self._client is None:
            if not os.getenv("LLAMA_CLOUD_API_KEY"):
                raise RuntimeError("LLAMA_CLOUD_API_KEY is not configured.")

            self._client = LlamaCloud()

        return self._client

    def supports(self, source: Source) -> bool:
        source_text = str(source)

        if source_text.startswith(("http://", "https://")):
            return False

        return Path(source).suffix.lower() in SOURCE_TYPES

    def parse(self, source: Source) -> ParsedDocument:
        path = Path(source).expanduser().resolve()
        self._validate(path)

        result = self.client.parsing.parse(
            tier=self.tier,
            version="latest",
            upload_file=path,
            expand=["markdown"],
            timeout=300,
        )

        sections = self._create_sections(result)
        source_type = SOURCE_TYPES[path.suffix.lower()]
        document_id = sha256(str(path).encode("utf-8")).hexdigest()

        images = ()

        if source_type == SourceType.IMAGE:
            images = (
                DocumentImage(
                    image_id=self._stable_id(
                        document_id,
                        "source-image",
                    ),
                    page_number=1,
                    path_or_url=str(path),
                ),
            )

        if not sections and not images:
            raise ValueError("LlamaParse returned no usable content.")

        return ParsedDocument(
            document_id=document_id,
            title=self._find_title(sections, path.stem),
            source_type=source_type,
            source_uri=str(path),
            sections=sections,
            images=images,
            metadata={
                "parser": self.name,
                "parser_version": version("llama-cloud"),
                "parser_tier": self.tier,
                "cloud_processing": True,
                "job_id": result.job.id,
                "page_count": len(sections),
            },
        )

    def _create_sections(self, result: object) -> tuple[DocumentSection, ...]:
        markdown_result = getattr(result, "markdown", None)
        pages = getattr(markdown_result, "pages", None) or []
        sections = []

        for page in pages:
            if not getattr(page, "success", False):
                continue

            markdown = page.markdown.strip()
            if not markdown:
                continue

            page_number = page.page_number

            sections.append(
                DocumentSection(
                    section_id=self._stable_id(
                        str(result.job.id),
                        page_number,
                        markdown,
                    ),
                    text=markdown,
                    page_number=page_number,
                )
            )

        return tuple(sections)

    def _validate(self, path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"Source not found: {path}")

        if path.suffix.lower() not in SOURCE_TYPES:
            raise ValueError(f"Unsupported source type: {path.suffix}")

        maximum_bytes = self.settings.maximum_file_size_mb * 1024 * 1024

        if path.stat().st_size > maximum_bytes:
            raise ValueError(
                f"Source exceeds {self.settings.maximum_file_size_mb} MB."
            )

    @staticmethod
    def _find_title(
        sections: tuple[DocumentSection, ...],
        fallback: str,
    ) -> str:
        heading_pattern = re.compile(r"^#\s+(.+)$", re.MULTILINE)

        for section in sections:
            match = heading_pattern.search(section.text)
            if match:
                return match.group(1).strip()

        return fallback

    @staticmethod
    def _stable_id(*parts: object) -> str:
        identity = ":".join(str(part) for part in parts)
        return sha256(identity.encode("utf-8")).hexdigest()
import re
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlparse

import httpx
import trafilatura

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app. ragv2.ingest.parsers.base import Source


class WebParser:
    name ="web"

    def __init__(
            self,
            rag_settings: RagSettings = settings,
            http_client: httpx.Client | None = None,
    ):
        self.settings = rag_settings
        self.http_client = http_client

    def supports(self, source: Source) -> bool:
        if isinstance(source, Path):
            return False

        parsed = urlparse(str(source))
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def parse(self, source: Source) -> ParsedDocument:
        url = str(source)

        if not self.supports(url):
            raise ValueError(f"Invalid URL: {url}")

        response = self._download(url)

        max_bytes = self.settings.maximum_file_size_mb * 1024 * 1024
        if len(response.content) > max_bytes:
            raise ValueError(
                f"Web document exceeds "
                f"{self.settings.maximum_file_size_mb} MB."
            )

        extracted = trafilatura.bare_extraction(
            response.text,
            url=str(response.url),
            output_format="python",
            with_metadata=True,
            include_comments=False,
            include_tables=True,
            include_links=True,
            deduplicate=True,
            favor_precision=True,
        )

        if extracted is None:
            raise ValueError(f"No useful content extracted from: {url}")

        content = (extracted.text or extracted.raw_text or "").strip()
        if not content:
            raise ValueError(f"Extracted web document is empty: {url}")

        canonical_url = str(response.url)
        document_id = sha256(canonical_url.encode("utf-8")).hexdigest()

        return ParsedDocument(
            document_id=document_id,
            title=extracted.title or urlparse(canonical_url).netloc,
            source_type=SourceType.WEB,
            source_uri=canonical_url,
            authors=self._authors(extracted.author),
            sections=tuple(
                self._create_sections(
                    extracted.body,
                    content,
                    document_id,
                )
            ),
            metadata={
                "parser": self.name,
                "parser_version": "1.0",
                "hostname": extracted.hostname,
                "description": extracted.description,
                "published_date": extracted.date,
                "content_type": response.headers.get("content-type"),
            },
        )

    def _download(self, url: str) -> httpx.Response:
        if self.http_client is not None:
            response = self.http_client.get(url)
        else:
            response = httpx.get(
                url,
                timeout=self.settings.request_timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "DARWIN-RAG/0.1"},
            )

        response.raise_for_status()
        return response

    @staticmethod
    def _authors(author: str | None) -> tuple[str, ...]:
        if not author:
            return ()

        return tuple(
            name.strip()
            for name in re.split(r"[,;]", author)
            if name.strip()
        )

    @staticmethod
    def _create_sections(
            body: object,
            fallback_text: str,
            document_id: str,
    ) -> list[DocumentSection]:
        sections: list[DocumentSection] = []
        heading_path: list[str] = []

        if body is not None:
            for element in body.iter():
                if not isinstance(element.tag, str):
                    continue

                tag = element.tag.split("}")[-1]
                content = " ".join(element.itertext()).strip()
                content = " ".join(content.split())

                if not content:
                    continue

                if tag == "head":
                    rendered_level = element.get("rend", "h1")
                    level_match = re.search(r"\d+", rendered_level)
                    level = int(level_match.group()) if level_match else 1

                    heading_path = heading_path[: level - 1]
                    heading_path.append(content)
                    continue

                if tag not in {"p", "item", "quote", "code"}:
                    continue

                section_id = sha256(
                    (
                        f"{document_id}:{len(sections)}:"
                        f"{tuple(heading_path)}:{content}"
                    ).encode("utf-8")
                ).hexdigest()

                sections.append(
                    DocumentSection(
                        section_id=section_id,
                        text=content,
                        heading_path=tuple(heading_path),
                    )
                )

        if sections:
            return sections

        return [
            DocumentSection(
                section_id=sha256(
                    f"{document_id}:fallback:{fallback_text}".encode("utf-8")
                ).hexdigest(),
                text=fallback_text,
            )
        ]





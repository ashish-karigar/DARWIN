import re
from hashlib import sha256
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.parsers.base import Source
from app.ragv2.ingest.security import URLSafetyPolicy


class WebParser:
    """Extracts public web pages without exposing protected networks."""

    name = "web"

    def __init__(
        self,
        rag_settings: RagSettings = settings,
        http_client: httpx.Client | None = None,
        url_policy: URLSafetyPolicy | None = None,
    ):
        self.settings = rag_settings
        self.http_client = http_client
        self.url_policy = url_policy or URLSafetyPolicy()

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
        safe_url = self.url_policy.validate(url)

        if self.http_client is not None:
            return self._follow_redirects(
                self.http_client,
                safe_url,
            )

        with httpx.Client(
            timeout=self.settings.request_timeout_seconds,
            follow_redirects=False,
            headers={"User-Agent": "DARWIN-RAG/0.1"},
        ) as client:
            return self._follow_redirects(client, safe_url)

    def _follow_redirects(
        self,
        client: httpx.Client,
        url: str,
    ) -> httpx.Response:
        current_url = url

        for redirect_count in range(
            self.settings.maximum_web_redirects + 1
        ):
            response = self._bounded_request(
                client,
                current_url,
            )

            if not response.is_redirect:
                response.raise_for_status()
                return response

            location = response.headers.get("location")
            if not location:
                response.raise_for_status()
                return response

            if redirect_count >= self.settings.maximum_web_redirects:
                raise ValueError(
                    "Web source exceeded the maximum redirect count."
                )

            current_url = self.url_policy.validate(
                urljoin(current_url, location)
            )

        raise RuntimeError("Unreachable redirect state.")

    def _bounded_request(
        self,
        client: httpx.Client,
        url: str,
    ) -> httpx.Response:
        maximum_bytes = (
            self.settings.maximum_file_size_mb * 1024 * 1024
        )

        with client.stream(
            "GET",
            url,
            follow_redirects=False,
        ) as response:
            declared_length = response.headers.get("content-length")
            if (
                declared_length is not None
                and declared_length.isdigit()
                and int(declared_length) > maximum_bytes
            ):
                raise ValueError(
                    "Web document exceeds "
                    f"{self.settings.maximum_file_size_mb} MB."
                )

            if response.is_redirect:
                return httpx.Response(
                    status_code=response.status_code,
                    headers=response.headers,
                    request=response.request,
                )

            response.raise_for_status()
            content = bytearray()

            for block in response.iter_bytes():
                if len(content) + len(block) > maximum_bytes:
                    raise ValueError(
                        "Web document exceeds "
                        f"{self.settings.maximum_file_size_mb} MB."
                    )
                content.extend(block)

            return httpx.Response(
                status_code=response.status_code,
                headers=response.headers,
                content=bytes(content),
                request=response.request,
            )

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




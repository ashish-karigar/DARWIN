import re
from hashlib import sha256

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    Chunk,
    ContentType,
    DocumentTable,
    ParsedDocument,
)
from app.ragv2.ingest.chunking.tokenizer import (
    TiktokenCounter,
    TokenCounter,
)


class TableChunker:
    """Splits Markdown tables by rows while repeating their headers."""

    content_type = ContentType.TABLE

    def __init__(
        self,
        rag_settings: RagSettings = settings,
        token_counter: TokenCounter | None = None,
    ):
        self.settings = rag_settings
        self.token_counter = token_counter or TiktokenCounter()

    def chunk(self, document: ParsedDocument) -> tuple[Chunk, ...]:
        chunks = []

        for table in document.tables:
            chunks.extend(self._chunk_table(document, table))

        return tuple(chunks)

    def _chunk_table(
        self,
        document: ParsedDocument,
        table: DocumentTable,
    ) -> list[Chunk]:
        lines = [
            line.strip()
            for line in table.markdown.splitlines()
            if line.strip()
        ]

        if not self._has_markdown_header(lines):
            return [
                self._create_chunk(
                    document=document,
                    table=table,
                    text=table.markdown,
                    chunk_index=0,
                    row_start=None,
                    row_end=None,
                )
            ]

        header = lines[:2]
        rows = list(enumerate(lines[2:]))
        groups: list[list[tuple[int, str]]] = []
        current_group: list[tuple[int, str]] = []

        for row in rows:
            candidate = current_group + [row]
            candidate_text = self._render(
                table,
                header,
                candidate,
            )

            if (
                current_group
                and self.token_counter.count(candidate_text)
                > self.settings.table_chunk_tokens
            ):
                groups.append(current_group)

                overlap_count = self.settings.table_chunk_overlap_rows
                overlap_rows = (
                    current_group[-overlap_count:]
                    if overlap_count > 0
                    else []
                )

                overlap_candidate = self._render(
                    table,
                    header,
                    overlap_rows + [row],
                )

                current_group = (
                    overlap_rows
                    if self.token_counter.count(overlap_candidate)
                       <= self.settings.table_chunk_tokens
                    else []
                )

            current_group.append(row)

        if current_group or not rows:
            groups.append(current_group)

        return [
            self._create_chunk(
                document=document,
                table=table,
                text=self._render(table, header, group),
                chunk_index=chunk_index,
                row_start=group[0][0] if group else None,
                row_end=group[-1][0] if group else None,
            )
            for chunk_index, group in enumerate(groups)
        ]

    def _create_chunk(
        self,
        document: ParsedDocument,
        table: DocumentTable,
        text: str,
        chunk_index: int,
        row_start: int | None,
        row_end: int | None,
    ) -> Chunk:
        token_count = self.token_counter.count(text)

        return Chunk(
            chunk_id=self._stable_id(
                document.document_id,
                table.table_id,
                chunk_index,
                text,
            ),
            document_id=document.document_id,
            parent_id=table.table_id,
            text=text,
            content_type=self.content_type,
            heading_path=table.heading_path,
            page_number=table.page_number,
            source_uri=document.source_uri,
            token_count=token_count,
            metadata={
                "chunk_index": chunk_index,
                "parent_type": "table",
                "document_title": document.title,
                "caption": table.caption,
                "row_start": row_start,
                "row_end": row_end,
                "oversized": (
                    token_count > self.settings.table_chunk_tokens
                ),
            },
        )

    @staticmethod
    def _render(
        table: DocumentTable,
        header: list[str],
        rows: list[tuple[int, str]],
    ) -> str:
        lines = []

        if table.caption:
            lines.extend([f"Caption: {table.caption}", ""])

        lines.extend(header)
        lines.extend(row_text for _, row_text in rows)

        return "\n".join(lines)

    @staticmethod
    def _has_markdown_header(lines: list[str]) -> bool:
        if len(lines) < 2:
            return False

        cells = lines[1].strip("|").split("|")

        return bool(cells) and all(
            re.fullmatch(r":?-{3,}:?", cell.strip())
            for cell in cells
        )

    @staticmethod
    def _stable_id(*parts: object) -> str:
        identity = ":".join(str(part) for part in parts)
        return sha256(identity.encode("utf-8")).hexdigest()
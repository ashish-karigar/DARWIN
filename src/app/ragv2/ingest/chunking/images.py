from hashlib import sha256

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    Chunk,
    ContentType,
    ParsedDocument,
)
from app.ragv2.ingest.chunking.tokenizer import (
    TiktokenCounter,
    TokenCounter,
)


class ImageChunker:
    """Converts image captions and descriptions into searchable text."""

    content_type = ContentType.IMAGE_DESCRIPTION

    def __init__(
        self,
        rag_settings: RagSettings = settings,
        token_counter: TokenCounter | None = None,
    ):
        self.settings = rag_settings
        self.token_counter = token_counter or TiktokenCounter()

        self.splitter = (
            RecursiveCharacterTextSplitter.from_tiktoken_encoder(
                encoding_name="cl100k_base",
                chunk_size=rag_settings.child_chunk_tokens,
                chunk_overlap=rag_settings.child_chunk_overlap_tokens,
                separators=["\n\n", "\n", ". ", " ", ""],
                keep_separator="end",
                disallowed_special=(),
            )
        )

    def chunk(self, document: ParsedDocument) -> tuple[Chunk, ...]:
        chunks = []

        for image in document.images:
            searchable_text = self._build_searchable_text(
                image.caption,
                image.description,
            )

            if not searchable_text:
                continue

            texts = self.splitter.split_text(searchable_text)

            for chunk_index, text in enumerate(texts):
                token_count = self.token_counter.count(text)

                if token_count == 0:
                    continue

                chunks.append(
                    Chunk(
                        chunk_id=self._stable_id(
                            document.document_id,
                            image.image_id,
                            chunk_index,
                            text,
                        ),
                        document_id=document.document_id,
                        parent_id=image.image_id,
                        text=text,
                        content_type=self.content_type,
                        heading_path=image.heading_path,
                        page_number=image.page_number,
                        source_uri=document.source_uri,
                        token_count=token_count,
                        metadata={
                            "chunk_index": chunk_index,
                            "parent_type": "image",
                            "document_title": document.title,
                            "image_path": image.path_or_url,
                        },
                    )
                )

        return tuple(chunks)

    @staticmethod
    def _build_searchable_text(
        caption: str | None,
        description: str | None,
    ) -> str:
        parts = []

        if caption:
            parts.append(f"Image caption: {caption.strip()}")

        if description and description.strip() != (caption or "").strip():
            parts.append(f"Image description: {description.strip()}")

        return "\n".join(parts)

    @staticmethod
    def _stable_id(*parts: object) -> str:
        identity = ":".join(str(part) for part in parts)
        return sha256(identity.encode("utf-8")).hexdigest()
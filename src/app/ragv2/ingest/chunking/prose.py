from hashlib import sha256

from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    Chunk,
    ContentType,
    ParsedDocument,
    SourceType,
)
from app.ragv2.ingest.chunking.tokenizer import (
    TiktokenCounter,
    TokenCounter,
)


class ProseChunker:
    """Splits document sections into overlapping searchable chunks."""

    content_type = ContentType.TEXT

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
                separators=[
                    "\n\n",
                    "\n",
                    ". ",
                    "? ",
                    "! ",
                    "; ",
                    ", ",
                    " ",
                    "",
                ],
                keep_separator="end",
                add_start_index=True,
                disallowed_special=(),
            )
        )

    def chunk(self, document: ParsedDocument) -> tuple[Chunk, ...]:
        if document.source_type == SourceType.CODE:
            return ()

        chunks = []

        for section in document.sections:
            split_documents = self.splitter.create_documents(
                [section.text]
            )

            for chunk_index, split_document in enumerate(
                split_documents
            ):
                text = split_document.page_content
                token_count = self.token_counter.count(text)

                if token_count == 0:
                    continue

                relative_start = split_document.metadata["start_index"]
                relative_end = relative_start + len(text)

                start_offset = None
                end_offset = None

                if section.start_offset is not None:
                    start_offset = section.start_offset + relative_start
                    end_offset = section.start_offset + relative_end

                chunks.append(
                    Chunk(
                        chunk_id=self._stable_id(
                            document.document_id,
                            section.section_id,
                            chunk_index,
                            text,
                        ),
                        document_id=document.document_id,
                        parent_id=section.section_id,
                        text=text,
                        content_type=self.content_type,
                        heading_path=section.heading_path,
                        page_number=section.page_number,
                        source_uri=document.source_uri,
                        start_offset=start_offset,
                        end_offset=end_offset,
                        token_count=token_count,
                        metadata={
                            "chunk_index": chunk_index,
                            "parent_type": "section",
                            "document_title": document.title,
                        },
                    )
                )

        return tuple(chunks)

    @staticmethod
    def _stable_id(*parts: object) -> str:
        identity = ":".join(str(part) for part in parts)
        return sha256(identity.encode("utf-8")).hexdigest()
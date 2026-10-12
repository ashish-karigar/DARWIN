"""Builds fingerprinted, benchmark-only DARWIN indexes.

Overview:
    External benchmark corpora must never enter the production collection.
    Each corpus is hashed into its own index directory. Interrupted ingests
    resume by skipping documents already present; changed corpora naturally
    receive a new directory and collection name.
"""

import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

from app.ragv2.config import RagSettings, settings as rag_settings
from app.ragv2.contracts import (
    DocumentSection,
    ParsedDocument,
    SourceType,
)
from app.ragv2.eval.industry.config import settings
from app.ragv2.eval.industry.datasets import iter_corpus
from app.ragv2.ingest.chunking.pipeline import ChunkingPipeline
from app.ragv2.ingest.indexes.document_store import SQLiteDocumentStore
from app.ragv2.ingest.indexes.lexical import SQLiteLexicalIndex
from app.ragv2.ingest.indexes.structured import SQLiteStructuredIndex
from app.ragv2.ingest.indexes.vector import ChromaVectorIndex


@dataclass(frozen=True, slots=True)
class IndexBuildReport:
    dataset: str
    fingerprint: str
    indexed_documents: int
    skipped_documents: int
    total_documents: int
    index_directory: Path
    rag_settings: RagSettings


def corpus_fingerprint(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while block := handle.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def build_isolated_settings(
    dataset: str,
    fingerprint: str,
) -> RagSettings:
    safe_name = re.sub(r"[^a-z0-9]+", "_", dataset.casefold()).strip(
        "_"
    )
    version = fingerprint[:12]
    index_directory = settings.index_root / safe_name / version

    return replace(
        rag_settings,
        document_store_path=index_directory / "documents.sqlite3",
        vector_index_directory=index_directory / "chroma",
        lexical_index_path=index_directory / "lexical.sqlite3",
        structured_index_path=index_directory / "structured.sqlite3",
        vector_collection_name=f"industry_{safe_name}_{version}",
        embedding_batch_size=int(
            os.getenv("DARWIN_INDUSTRY_EMBEDDING_BATCH_SIZE", "128")
        ),
    )


def ensure_dataset_index(
    dataset: str,
    *,
    processed_root: Path = settings.processed_root,
    progress: bool = False,
) -> IndexBuildReport:
    corpus_path = processed_root / dataset / "corpus.jsonl"
    if not corpus_path.is_file():
        raise FileNotFoundError(
            f"Processed corpus not found: {corpus_path}"
        )

    fingerprint = corpus_fingerprint(corpus_path)
    isolated = build_isolated_settings(dataset, fingerprint)
    index_directory = isolated.document_store_path.parent
    index_directory.mkdir(parents=True, exist_ok=True)

    document_store = SQLiteDocumentStore(
        isolated.document_store_path
    )
    vector_index = ChromaVectorIndex(isolated)
    lexical_index = SQLiteLexicalIndex(
        isolated.lexical_index_path
    )
    structured_index = SQLiteStructuredIndex(
        isolated.structured_index_path
    )
    chunker = ChunkingPipeline()
    indexed = 0
    skipped = 0
    pending_documents = []
    pending_chunks = []
    chunk_batch_size = max(32, isolated.embedding_batch_size * 8)

    def flush_batch() -> int:
        if not pending_chunks:
            return 0
        # Search representations are written before the document checkpoint.
        # If the process stops midway, a retry safely upserts them again. Once
        # a document exists in the store, all of its searchable chunks do too.
        vector_index.upsert(tuple(pending_chunks))
        lexical_index.upsert(tuple(pending_chunks))
        for pending_document in pending_documents:
            structured_index.upsert(pending_document)
            document_store.store(pending_document)
        completed = len(pending_documents)
        pending_documents.clear()
        pending_chunks.clear()
        return completed

    for number, record in enumerate(
        iter_corpus(processed_root, dataset),
        start=1,
    ):
        document_id = f"{dataset}:{record['doc_id']}"
        if document_store.get_document(document_id) is not None:
            skipped += 1
            continue

        document = ParsedDocument(
            document_id=document_id,
            title=record["title"],
            source_type=SourceType.TEXT,
            source_uri=f"benchmark://{dataset}/{record['doc_id']}",
            sections=(
                DocumentSection(
                    section_id=f"{document_id}:section:0",
                    text=record["text"],
                ),
            ),
            metadata={
                "benchmark_dataset": dataset,
                "benchmark_doc_id": record["doc_id"],
                "corpus_fingerprint": fingerprint,
            },
        )
        chunks = chunker.chunk(document).chunks
        pending_documents.append(document)
        pending_chunks.extend(chunks)

        if len(pending_chunks) >= chunk_batch_size:
            indexed += flush_batch()
            if progress:
                print(
                    f"[{dataset}] indexed {indexed}, resumed {skipped}"
                )

    indexed += flush_batch()
    if progress:
        print(f"[{dataset}] indexed {indexed}, resumed {skipped}")

    total = document_store.count_documents()
    manifest = {
        "dataset": dataset,
        "corpus": str(corpus_path),
        "fingerprint": fingerprint,
        "document_count": total,
        "vector_chunk_count": vector_index.count(),
        "lexical_chunk_count": lexical_index.count(),
    }
    (index_directory / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    return IndexBuildReport(
        dataset=dataset,
        fingerprint=fingerprint,
        indexed_documents=indexed,
        skipped_documents=skipped,
        total_documents=total,
        index_directory=index_directory,
        rag_settings=isolated,
    )

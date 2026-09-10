from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import tiktoken
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter


DATABASE_PATH = "data/chroma_v2"
EMBEDDING_MODEL = "nomic-embed-text"
DOCUMENTS = {
    Path("data/knowledge.txt"): "darwin_knowledge",
    Path("data/tasks.txt"): "tasks",
}

embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)
tokenizer = tiktoken.get_encoding("cl100k_base")
splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
    encoding_name="cl100k_base",
    chunk_size=220,
    chunk_overlap=40,
)


def _logical_sections(text: str, collection_name: str) -> list[str]:
    if collection_name == "tasks":
        return [line.strip() for line in text.splitlines() if line.strip()]

    return [section.strip() for section in text.split("\n\n") if section.strip()]


def _chunks(text: str, collection_name: str) -> list[tuple[int, str]]:
    output: list[tuple[int, str]] = []
    for section_index, section in enumerate(_logical_sections(text, collection_name)):
        for chunk in splitter.split_text(section):
            if chunk.strip():
                output.append((section_index, chunk.strip()))
    return output


def ingest_document(document_path: Path, collection_name: str) -> int:
    if not document_path.exists():
        raise FileNotFoundError(f"Document not found: {document_path}")

    text = document_path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Document is empty: {document_path}")

    chunks = _chunks(text, collection_name)
    document_hash = sha256(text.encode("utf-8")).hexdigest()
    ingested_at = datetime.now(timezone.utc).isoformat()

    vector_store = Chroma(
        collection_name=collection_name,
        embedding_function=embeddings,
        persist_directory=DATABASE_PATH,
        collection_metadata={"hnsw:space": "cosine"},
    )

    existing = vector_store.get(where={"source": str(document_path)})
    if existing["ids"]:
        vector_store.delete(ids=existing["ids"])

    ids = [
        sha256(
            f"{document_path}:{document_hash}:{section_index}:{chunk_index}".encode()
        ).hexdigest()
        for chunk_index, (section_index, _) in enumerate(chunks)
    ]
    metadata = [
        {
            "source": str(document_path),
            "source_name": document_path.name,
            "collection": collection_name,
            "section_index": section_index,
            "chunk_index": chunk_index,
            "document_hash": document_hash,
            "ingested_at": ingested_at,
            "token_count": len(tokenizer.encode(chunk)),
            "embedding_model": EMBEDDING_MODEL,
        }
        for chunk_index, (section_index, chunk) in enumerate(chunks)
    ]

    vector_store.add_texts(
        texts=[chunk for _, chunk in chunks],
        metadatas=metadata,
        ids=ids,
    )
    return len(chunks)


def ingest_all() -> dict[str, int]:
    results = {}
    for document_path, collection_name in DOCUMENTS.items():
        count = ingest_document(document_path, collection_name)
        results[collection_name] = count
        print(f"Ingested {count} chunks from {document_path} into {collection_name}.")
    return results


if __name__ == "__main__":
    ingest_all()

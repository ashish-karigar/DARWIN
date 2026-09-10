from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import re
from time import monotonic

from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

from app.rag.ingest import DATABASE_PATH, EMBEDDING_MODEL
from app.services.telemetry import record_retrieval


DEFAULT_LIMIT = 3
DEFAULT_SCORE_THRESHOLD = 0.55
SEMANTIC_WEIGHT = 0.60
LEXICAL_WEIGHT = 0.40
STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "darwin",
    "does",
    "for",
    "gives",
    "is",
    "it",
    "kind",
    "of",
    "project",
    "service",
    "the",
    "to",
    "use",
    "uses",
    "what",
    "when",
    "which",
    "who",
    "with",
}
SYNONYMS = {
    "speak": {"speech", "voice", "tts"},
    "voice": {"speech", "speak", "tts"},
    "speech": {"voice", "speak", "tts"},
    "database": {"storage", "store", "chromadb"},
    "storage": {"database", "store", "chromadb"},
    "application": {"assistant", "system"},
    "assistant": {"application", "system"},
}

embeddings = OllamaEmbeddings(model=EMBEDDING_MODEL)
vector_stores = {
    collection: Chroma(
        collection_name=collection,
        embedding_function=embeddings,
        persist_directory=DATABASE_PATH,
        collection_metadata={"hnsw:space": "cosine"},
    )
    for collection in ("darwin_knowledge", "tasks")
}


@dataclass(frozen=True)
class RetrievalResult:
    content: str
    score: float
    semantic_score: float
    lexical_score: float
    source: str
    chunk_index: int

    def to_dict(self) -> dict:
        return asdict(self)


def retrieve(
    query: str,
    collection_name: str,
    limit: int = DEFAULT_LIMIT,
    score_threshold: float = DEFAULT_SCORE_THRESHOLD,
) -> list[RetrievalResult]:
    query = query.strip()
    if not query:
        raise ValueError("Retrieval query cannot be empty.")
    if collection_name not in vector_stores:
        raise ValueError(f"Unknown collection: {collection_name}")

    limit = max(1, min(limit, 10))
    started = monotonic()
    matches = vector_stores[collection_name].similarity_search_with_relevance_scores(
        query,
        k=max(12, limit * 4),
    )

    def stem(token: str) -> str:
        for suffix in ("ing", "ed", "es", "s"):
            if token.endswith(suffix) and len(token) > len(suffix) + 2:
                return token[: -len(suffix)]
        return token

    def terms(value: str) -> set[str]:
        return {
            stem(token)
            for token in re.findall(r"[a-z0-9]+", value.casefold())
            if token not in STOP_WORDS and len(token) > 1
        }

    def lexical_coverage(query_tokens: set[str], document_tokens: set[str]) -> float:
        if not query_tokens:
            return 0.0
        matched = 0
        for token in query_tokens:
            variants = {token, *SYNONYMS.get(token, set())}
            if variants & document_tokens:
                matched += 1
        return matched / len(query_tokens)

    query_terms = terms(query)
    ranked = []
    for document, semantic_score in matches:
        document_terms = terms(document.page_content)
        lexical_score = lexical_coverage(query_terms, document_terms)
        combined_score = (
            SEMANTIC_WEIGHT * float(semantic_score) + LEXICAL_WEIGHT * lexical_score
        )
        ranked.append((document, semantic_score, lexical_score, combined_score))

    ranked.sort(key=lambda item: item[3], reverse=True)
    results = [
        RetrievalResult(
            content=document.page_content,
            score=round(float(combined_score), 4),
            semantic_score=round(float(semantic_score), 4),
            lexical_score=round(float(lexical_score), 4),
            source=str(document.metadata.get("source", "unknown")),
            chunk_index=int(document.metadata.get("chunk_index", -1)),
        )
        for document, semantic_score, lexical_score, combined_score in ranked
        if combined_score >= score_threshold
    ][:limit]
    latency = monotonic() - started

    record_retrieval(
        query_hash=sha256(query.encode("utf-8")).hexdigest(),
        collection_name=collection_name,
        latency_seconds=latency,
        requested_k=limit,
        returned_count=len(results),
        top_score=results[0].score if results else None,
        score_threshold=score_threshold,
    )
    return results


def search_collection(
    query: str,
    collection_name: str,
    limit: int = DEFAULT_LIMIT,
) -> str:
    results = retrieve(query, collection_name, limit=limit)
    if not results:
        return "No relevant information found."
    return "\n\n".join(result.content for result in results)


def search_knowledge(query: str) -> str:
    return search_collection(query, "darwin_knowledge")


def search_tasks(query: str) -> str:
    """Tasks use their structured source for complete and exact status reporting."""
    return Path("data/tasks.txt").read_text(encoding="utf-8")

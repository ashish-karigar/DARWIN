"""Benchmarks DARWIN's hybrid retrieval against BEIR SciFact.

Deliberately NOT part of the production eval harness (evaluate.py):
that harness's CaseResult/EvaluationReport contracts are built around
DARWIN's own answer-quality grading (binary suffix-match hit@1/hit@5,
no graded relevance) and are exercised by a hardened test suite this
script has no business touching. This reuses only the low-level
retrieval primitives -- HybridRetriever, CrossEncoderReranker, the
chunking/indexing pipelines -- against a fully isolated index, so the
benchmark corpus never reaches DARWIN's real, production knowledge
base.

The measurement bypasses QueryAnalyzer and EvidenceGrader on purpose:
published "45-65% NDCG@10 for strong dense retrievers" figures measure
the retriever alone, not an LLM-orchestrated pipeline that rewrites or
grades queries first. This calls DARWIN's actual retrieval stack
(dense+lexical fusion, then cross-encoder rerank) the same way the
literature measures retrievers, so the resulting number is honestly
comparable.

Usage:
    python -m app.ragv2.eval.beir_benchmark --progress
    python -m app.ragv2.eval.beir_benchmark --skip-ingest --query-limit 20
"""

import argparse
import json
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from math import log2
from pathlib import Path

from app.ragv2.config import PROJECT_ROOT, RagSettings
from app.ragv2.contracts import DocumentSection, ParsedDocument, SourceType
from app.ragv2.ingest.chunking.pipeline import ChunkingPipeline
from app.ragv2.ingest.indexes.document_store import SQLiteDocumentStore
from app.ragv2.ingest.indexes.lexical import SQLiteLexicalIndex
from app.ragv2.ingest.indexes.pipeline import IndexingPipeline
from app.ragv2.ingest.indexes.structured import SQLiteStructuredIndex
from app.ragv2.ingest.indexes.vector import ChromaVectorIndex
from app.ragv2.retrieve.retrieval.hybrid import HybridRetriever
from app.ragv2.retrieve.retrieval.reranker import CrossEncoderReranker

DEFAULT_DATA_DIR = (
    PROJECT_ROOT / "data" / "ragv2" / "benchmarks" / "scifact"
)
CANDIDATE_POOL_SIZE = 100
RANK_CUTOFF = 10


def build_isolated_settings(data_dir: Path) -> RagSettings:
    """A RagSettings pointing entirely at benchmark-only index paths.

    Ingesting BEIR's unrelated scientific-abstract corpus into
    DARWIN's default index would contaminate the same index its real
    chat pipeline queries. Every store this script touches is
    constructed from this settings object, never the global default.
    """

    index_dir = data_dir / "indexes"
    return RagSettings(
        document_store_path=index_dir / "documents.sqlite3",
        vector_index_directory=index_dir / "chroma",
        lexical_index_path=index_dir / "lexical.sqlite3",
        structured_index_path=index_dir / "structured.sqlite3",
        vector_collection_name="beir_scifact",
    )


def _read_jsonl(path: Path):
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                yield json.loads(line)


def load_queries(path: Path) -> dict[str, str]:
    return {
        record["_id"]: record["text"]
        for record in _read_jsonl(path)
    }


def load_qrels(path: Path) -> dict[str, dict[str, int]]:
    """Parses a BEIR qrels TSV: query-id, corpus-id, score (0/1/2)."""

    qrels: dict[str, dict[str, int]] = defaultdict(dict)

    with path.open(encoding="utf-8") as handle:
        next(handle)  # header row

        for line in handle:
            line = line.strip()
            if not line:
                continue

            query_id, corpus_id, score = line.split("\t")
            qrels[query_id][corpus_id] = int(score)

    return dict(qrels)


def ingest_corpus(
    corpus_path: Path,
    indexing_pipeline: IndexingPipeline,
    *,
    progress: bool = False,
) -> int:
    """Builds a ParsedDocument per BEIR corpus record and indexes it.

    No parser needed: a BEIR record already IS the plain title+text
    a parser would otherwise extract, so this constructs the contract
    directly -- the same pattern test_rag_ingestor.py uses for
    synthetic test documents.
    """

    chunking_pipeline = ChunkingPipeline()
    count = 0

    for record in _read_jsonl(corpus_path):
        doc_id = record["_id"]
        title = (record.get("title") or "").strip() or doc_id
        text = (record.get("text") or "").strip() or title

        document = ParsedDocument(
            document_id=doc_id,
            title=title,
            source_type=SourceType.TEXT,
            source_uri=doc_id,
            sections=(
                DocumentSection(
                    section_id=f"{doc_id}:0",
                    text=text,
                ),
            ),
        )
        chunks = chunking_pipeline.chunk(document).chunks
        indexing_pipeline.index(document, chunks)
        count += 1

        if progress and count % 500 == 0:
            print(f"  ingested {count} documents...")

    return count


def _dedupe_preserving_order(document_ids) -> list[str]:
    """Keeps each document's first (highest-ranked) occurrence only.

    A reranked hit list is per-chunk; qrels and NDCG/Recall are
    defined per-document. Without this, one document contributing
    several chunks to the same top-K window gets its relevance grade
    counted multiple times, which can push NDCG above 1.0 -- a real
    bug this caught in an earlier version of this script.
    """

    return list(dict.fromkeys(document_ids))


def recall_at_k(
    ranked_ids: list[str],
    relevant_ids: set[str],
    k: int,
) -> float:
    if not relevant_ids:
        return 0.0

    return 1.0 if relevant_ids.intersection(ranked_ids[:k]) else 0.0


def ndcg_at_k(
    ranked_ids: list[str],
    grades: dict[str, int],
    k: int,
) -> float:
    """Standard graded DCG/IDCG, k truncated."""

    dcg = sum(
        grades.get(doc_id, 0) / log2(position + 2)
        for position, doc_id in enumerate(ranked_ids[:k])
    )
    ideal_grades = sorted(grades.values(), reverse=True)[:k]
    idcg = sum(
        grade / log2(position + 2)
        for position, grade in enumerate(ideal_grades)
    )
    return dcg / idcg if idcg > 0 else 0.0


@dataclass(frozen=True, slots=True)
class QueryResult:
    query_id: str
    recall_at_10: float
    ndcg_at_10: float
    latency_seconds: float


def run_benchmark(
    data_dir: Path,
    *,
    query_limit: int | None,
    progress: bool,
) -> tuple[QueryResult, ...]:
    isolated_settings = build_isolated_settings(data_dir)
    retriever = HybridRetriever(rag_settings=isolated_settings)
    reranker = CrossEncoderReranker(rag_settings=isolated_settings)

    queries = load_queries(data_dir / "raw" / "queries.jsonl")
    qrels = load_qrels(data_dir / "raw" / "qrels" / "test.tsv")

    query_ids = [
        query_id for query_id in qrels if query_id in queries
    ]
    if query_limit is not None:
        query_ids = query_ids[:query_limit]

    results = []

    for index, query_id in enumerate(query_ids, start=1):
        question = queries[query_id]
        grades = qrels[query_id]
        relevant_ids = {
            doc_id for doc_id, grade in grades.items() if grade >= 1
        }

        started = time.perf_counter()
        candidates = retriever.search(
            question,
            limit=CANDIDATE_POOL_SIZE,
        )
        # Rerank the whole pool, not just the top 10: BEIR qrels are
        # per-document, but reranked hits are per-chunk, and one
        # document can legitimately place multiple chunks in a top-10
        # slice. Deduping AFTER truncating to 10 would silently return
        # fewer than 10 candidate documents; deduping the full pool
        # first, then taking the top 10 *unique* documents, is what
        # keeps this a fair document-level top-10.
        reranked = reranker.rerank(
            question,
            candidates,
            limit=CANDIDATE_POOL_SIZE,
        )
        elapsed = time.perf_counter() - started

        ranked_ids = _dedupe_preserving_order(
            hit.chunk.document_id for hit in reranked
        )
        result = QueryResult(
            query_id=query_id,
            recall_at_10=recall_at_k(
                ranked_ids, relevant_ids, RANK_CUTOFF
            ),
            ndcg_at_10=ndcg_at_k(ranked_ids, grades, RANK_CUTOFF),
            latency_seconds=elapsed,
        )
        results.append(result)

        if progress:
            print(
                f"[{index}/{len(query_ids)}] {query_id}: "
                f"recall@10={result.recall_at_10:.0f} "
                f"ndcg@10={result.ndcg_at_10:.3f} "
                f"({elapsed:.2f}s)"
            )

    return tuple(results)


def summarize(results: tuple[QueryResult, ...]) -> None:
    print()
    print("BEIR SciFact benchmark: COMPLETED")

    if not results:
        print("No queries evaluated.")
        return

    mean_recall = sum(r.recall_at_10 for r in results) / len(results)
    mean_ndcg = sum(r.ndcg_at_10 for r in results) / len(results)
    mean_latency = (
        sum(r.latency_seconds for r in results) / len(results)
    )

    print(f"Queries evaluated:  {len(results)}")
    print(f"Mean Recall@10:     {mean_recall * 100:.2f}%")
    print(f"Mean NDCG@10:       {mean_ndcg * 100:.2f}%")
    print(f"Mean latency:       {mean_latency:.2f}s")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark DARWIN's hybrid retrieval against BEIR SciFact."
        ),
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=(
            "Directory containing raw/corpus.jsonl, raw/queries.jsonl, "
            "raw/qrels/test.tsv"
        ),
    )
    parser.add_argument(
        "--skip-ingest",
        action="store_true",
        help="Reuse an already-ingested isolated index.",
    )
    parser.add_argument(
        "--query-limit",
        type=int,
        default=None,
        help="Only evaluate the first N test queries (quick sanity run).",
    )
    parser.add_argument("--progress", action="store_true")
    parser.add_argument("--output", type=Path, default=None)
    arguments = parser.parse_args()

    if not arguments.skip_ingest:
        isolated_settings = build_isolated_settings(
            arguments.data_dir
        )
        indexing_pipeline = IndexingPipeline(
            document_store=SQLiteDocumentStore(
                isolated_settings.document_store_path
            ),
            vector_index=ChromaVectorIndex(isolated_settings),
            lexical_index=SQLiteLexicalIndex(
                isolated_settings.lexical_index_path
            ),
            structured_index=SQLiteStructuredIndex(
                isolated_settings.structured_index_path
            ),
        )
        print(
            "Ingesting BEIR SciFact corpus into an isolated index "
            f"(never touches DARWIN's production index)..."
        )
        count = ingest_corpus(
            arguments.data_dir / "raw" / "corpus.jsonl",
            indexing_pipeline,
            progress=arguments.progress,
        )
        print(f"Ingested {count} documents.")

    results = run_benchmark(
        arguments.data_dir,
        query_limit=arguments.query_limit,
        progress=arguments.progress,
    )
    summarize(results)

    if arguments.output:
        arguments.output.write_text(
            json.dumps(
                [asdict(result) for result in results],
                indent=2,
            )
        )
        print(f"Detailed results written to {arguments.output}")


if __name__ == "__main__":
    main()

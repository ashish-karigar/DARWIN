"""Runs DARWIN's retriever against representative BEIR datasets.

Overview:
    BEIR measures retrieval rather than answer generation. This adapter
    downloads the official archives, converts them to DARWIN's isolated index
    format, resumes query retrieval from JSONL, and computes standard nDCG,
    MAP, recall, precision, and MRR without using an LLM judge.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

from app.ragv2.eval.industry.config import REPRESENTATIVE_BEIR_DATASETS, settings
from app.ragv2.eval.industry.indexing import ensure_dataset_index
from app.ragv2.retrieve.retrieval.hybrid import HybridRetriever


BEIR_BASE_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets"
DEFAULT_K_VALUES = (1, 3, 5, 10, 100)


def download_beir(dataset: str) -> Path:
    _validate_dataset(dataset)
    download_root = settings.external_root.parent / "beir" / "downloads"
    raw_root = settings.external_root.parent / "beir" / "raw"
    download_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    archive = download_root / f"{dataset}.zip"
    destination = raw_root / dataset

    if not archive.is_file():
        urllib.request.urlretrieve(f"{BEIR_BASE_URL}/{dataset}.zip", archive)
    if not destination.is_dir():
        with zipfile.ZipFile(archive) as bundle:
            root = raw_root.resolve()
            for member in bundle.infolist():
                target = (raw_root / member.filename).resolve()
                if root not in target.parents and target != root:
                    raise ValueError("Unsafe path found in BEIR archive.")
            bundle.extractall(raw_root)
    if not destination.is_dir():
        raise FileNotFoundError(f"BEIR archive did not create {destination}.")
    return destination


def prepare_beir(dataset: str, raw_directory: str | Path | None = None) -> tuple[int, int]:
    _validate_dataset(dataset)
    source = Path(raw_directory) if raw_directory else download_beir(dataset)
    name = f"beir_{dataset}"
    destination = settings.processed_root / name
    destination.mkdir(parents=True, exist_ok=True)

    corpus_count = _copy_jsonl_corpus(source / "corpus.jsonl", destination / "corpus.jsonl")
    queries = _load_jsonl_map(source / "queries.jsonl", text_key="text")
    qrels = _read_qrels(source / "qrels" / "test.tsv")
    selected_queries = {
        query_id: text for query_id, text in queries.items() if query_id in qrels
    }
    (destination / "queries.json").write_text(
        json.dumps(selected_queries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (destination / "qrels.json").write_text(
        json.dumps(qrels, indent=2),
        encoding="utf-8",
    )
    return corpus_count, len(selected_queries)


def run_beir(
    dataset: str,
    *,
    top_k: int = 100,
    limit: int | None = None,
    progress: bool = False,
) -> dict:
    _validate_dataset(dataset)
    name = f"beir_{dataset}"
    directory = settings.processed_root / name
    queries = json.loads((directory / "queries.json").read_text(encoding="utf-8"))
    qrels = json.loads((directory / "qrels.json").read_text(encoding="utf-8"))
    index = ensure_dataset_index(name, progress=progress)
    retriever = HybridRetriever(rag_settings=index.rag_settings)

    run_directory = settings.run_root / name
    run_directory.mkdir(parents=True, exist_ok=True)
    checkpoint_path = run_directory / "retrieval.jsonl"
    results = _load_retrieval_checkpoint(checkpoint_path)
    pending = [(qid, text) for qid, text in queries.items() if qid not in results]
    if limit is not None:
        pending = pending[:limit]

    with checkpoint_path.open("a", encoding="utf-8") as checkpoint:
        for number, (query_id, query) in enumerate(pending, start=1):
            hits = retriever.search(query, limit=top_k)
            documents = {}
            for hit in hits:
                document_id = hit.chunk.document_id.removeprefix(f"{name}:")
                documents.setdefault(document_id, float(hit.score))
            results[query_id] = documents
            checkpoint.write(
                json.dumps({"query_id": query_id, "results": documents}) + "\n"
            )
            checkpoint.flush()
            if progress and (number % 25 == 0 or number == len(pending)):
                completed = len(results)
                print(
                    f"[{completed}/{len(queries)}] {dataset}: "
                    f"retrieved {number}/{len(pending)} pending queries"
                )

    evaluated_qrels = {qid: qrels[qid] for qid in results if qid in qrels}
    evaluated_results = {qid: results[qid] for qid in evaluated_qrels}
    metrics = evaluate_retrieval(evaluated_qrels, evaluated_results)
    payload = {
        "dataset": dataset,
        "query_count": len(evaluated_qrels),
        "corpus_fingerprint": index.fingerprint,
        "top_k": top_k,
        "metrics": metrics,
    }
    report_path = settings.report_root / "beir" / f"{dataset}.json"
    _write_beir_report(payload, report_path)
    return payload


def evaluate_retrieval(qrels: dict, results: dict, k_values=DEFAULT_K_VALUES) -> dict:
    totals = defaultdict(float)
    query_count = len(qrels)
    if query_count == 0:
        raise ValueError("No BEIR queries are available for evaluation.")

    for query_id, relevance in qrels.items():
        relevant = {doc_id for doc_id, score in relevance.items() if int(score) > 0}
        ranked = sorted(results.get(query_id, {}).items(), key=lambda item: item[1], reverse=True)
        ranked_ids = [doc_id for doc_id, _ in ranked]
        first_relevant_rank = next(
            (rank for rank, doc_id in enumerate(ranked_ids, 1) if doc_id in relevant),
            None,
        )
        for k in k_values:
            top = ranked_ids[:k]
            hit_count = sum(doc_id in relevant for doc_id in top)
            gains = [float(relevance.get(doc_id, 0)) for doc_id in top]
            ideal = sorted((float(score) for score in relevance.values()), reverse=True)[:k]
            dcg = sum((2**gain - 1) / math.log2(rank + 1) for rank, gain in enumerate(gains, 1))
            idcg = sum((2**gain - 1) / math.log2(rank + 1) for rank, gain in enumerate(ideal, 1))
            precision_sum = 0.0
            seen_relevant = 0
            for rank, doc_id in enumerate(top, 1):
                if doc_id in relevant:
                    seen_relevant += 1
                    precision_sum += seen_relevant / rank
            totals[f"NDCG@{k}"] += dcg / idcg if idcg else 0.0
            totals[f"MAP@{k}"] += precision_sum / min(len(relevant), k) if relevant else 0.0
            totals[f"Recall@{k}"] += hit_count / len(relevant) if relevant else 0.0
            totals[f"P@{k}"] += hit_count / k
            totals[f"MRR@{k}"] += (
                1 / first_relevant_rank
                if first_relevant_rank is not None and first_relevant_rank <= k
                else 0.0
            )
    return {name: round(value / query_count, 5) for name, value in sorted(totals.items())}


def _copy_jsonl_corpus(source: Path, destination: Path) -> int:
    count = 0
    with source.open(encoding="utf-8") as input_handle, destination.open("w", encoding="utf-8") as output:
        for line in input_handle:
            if not line.strip():
                continue
            record = json.loads(line)
            output.write(
                json.dumps(
                    {
                        "doc_id": str(record["_id"]),
                        "title": record.get("title") or str(record["_id"]),
                        "text": record.get("text") or "",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            count += 1
    return count


def _load_jsonl_map(path: Path, *, text_key: str) -> dict[str, str]:
    with path.open(encoding="utf-8") as handle:
        return {
            str(record["_id"]): str(record[text_key])
            for record in (json.loads(line) for line in handle if line.strip())
        }


def _read_qrels(path: Path) -> dict[str, dict[str, int]]:
    qrels = defaultdict(dict)
    with path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        for row in reader:
            query_id = row.get("query-id") or row.get("query_id")
            corpus_id = row.get("corpus-id") or row.get("corpus_id")
            qrels[str(query_id)][str(corpus_id)] = int(row["score"])
    return dict(qrels)


def _load_retrieval_checkpoint(path: Path) -> dict[str, dict[str, float]]:
    if not path.is_file():
        return {}
    results = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                record = json.loads(line)
                results[record["query_id"]] = record["results"]
    return results


def _write_beir_report(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    rows = list(payload["metrics"].items())
    with path.with_suffix(".csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("metric", "score"))
        writer.writerows(rows)
    markdown = [
        f"# BEIR: {payload['dataset']}",
        "",
        f"Queries evaluated: {payload['query_count']}",
        "",
        "| Metric | Score |",
        "|---|---:|",
    ]
    markdown.extend(f"| {name} | {value} |" for name, value in rows)
    path.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8")


def _validate_dataset(dataset: str) -> None:
    if dataset not in REPRESENTATIVE_BEIR_DATASETS:
        raise ValueError(
            f"Unsupported BEIR dataset {dataset!r}; choose from {REPRESENTATIVE_BEIR_DATASETS}."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare or run representative BEIR datasets.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("dataset", choices=REPRESENTATIVE_BEIR_DATASETS)
    run = subparsers.add_parser("run")
    run.add_argument("dataset", choices=REPRESENTATIVE_BEIR_DATASETS)
    run.add_argument("--top-k", type=int, default=100)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--progress", action="store_true")
    arguments = parser.parse_args()

    if arguments.command == "prepare":
        documents, queries = prepare_beir(arguments.dataset)
        print(f"{arguments.dataset}: {documents} documents, {queries} test queries")
    else:
        report = run_beir(
            arguments.dataset,
            top_k=arguments.top_k,
            limit=arguments.limit,
            progress=arguments.progress,
        )
        print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

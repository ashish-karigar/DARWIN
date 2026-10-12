"""Validates and reports the complete external benchmark inventory."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from app.ragv2.eval.industry.config import REPRESENTATIVE_BEIR_DATASETS, settings
from app.ragv2.eval.industry.datasets import load_cases


RAGCHECKER_DATASETS = (
    "bioasq",
    "clapnq",
    "fiqa",
    "kiwi",
    "novelqa",
    "lifestyle",
    "science",
    "writing",
    "recreation",
    "technology",
)


def build_inventory() -> dict:
    records = []
    for dataset in RAGCHECKER_DATASETS:
        records.append(_record("ragchecker", dataset, expects_answers=True))
    for dataset in REPRESENTATIVE_BEIR_DATASETS:
        records.append(_record("beir", f"beir_{dataset}", expects_answers=False))
    return {
        "ready": all(record["ready"] for record in records),
        "dataset_count": len(records),
        "records": records,
    }


def write_inventory(payload: dict, output_path: str | Path) -> tuple[Path, Path, Path]:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    csv_path = path.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=payload["records"][0].keys())
        writer.writeheader()
        writer.writerows(payload["records"])
    markdown_path = path.with_suffix(".md")
    lines = [
        "# Industry benchmark inventory",
        "",
        f"Overall ready: **{'yes' if payload['ready'] else 'no'}**",
        "",
        "| Suite | Dataset | Ready | Documents | Questions | Corpus size |",
        "|---|---|:---:|---:|---:|---:|",
    ]
    for record in payload["records"]:
        lines.append(
            "| {suite} | {dataset} | {ready} | {document_count} | {query_count} | {corpus_bytes} |".format(
                **record
            )
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path, csv_path, markdown_path


def _record(suite: str, dataset: str, *, expects_answers: bool) -> dict:
    directory = settings.processed_root / dataset
    corpus_path = directory / "corpus.jsonl"
    query_count = 0
    query_ready = False
    if expects_answers:
        try:
            query_count = len(load_cases(settings.processed_root, dataset))
            query_ready = query_count > 0
        except (FileNotFoundError, ValueError):
            pass
    else:
        query_path = directory / "queries.json"
        if query_path.is_file():
            query_count = len(json.loads(query_path.read_text(encoding="utf-8")))
            query_ready = query_count > 0

    document_count = 0
    if corpus_path.is_file():
        with corpus_path.open(encoding="utf-8") as handle:
            document_count = sum(1 for line in handle if line.strip())
    return {
        "suite": suite,
        "dataset": dataset.removeprefix("beir_"),
        "ready": bool(document_count and query_ready),
        "document_count": document_count,
        "query_count": query_count,
        "corpus_bytes": corpus_path.stat().st_size if corpus_path.is_file() else 0,
    }


def main() -> None:
    payload = build_inventory()
    artifacts = write_inventory(
        payload,
        settings.report_root / "benchmark_inventory.json",
    )
    for artifact in artifacts:
        print(f"Artifact: {artifact}")
    if not payload["ready"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

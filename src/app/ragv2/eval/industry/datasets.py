"""Loads RAGChecker's processed QA and corpus files.

RAGChecker stores questions per domain as ``*_queries.json`` and documents as
``corpus.jsonl``. This module validates those files and exposes stable DARWIN
contracts without importing the RAGChecker package.
"""

import json
from collections.abc import Iterator
from pathlib import Path

from app.ragv2.eval.industry.contracts import BenchmarkCase


def discover_datasets(processed_root: str | Path) -> tuple[str, ...]:
    root = Path(processed_root)
    names = []

    if not root.exists():
        return ()

    for directory in sorted(root.iterdir()):
        if not directory.is_dir():
            continue
        if _query_path(directory) is not None:
            names.append(directory.name)

    return tuple(names)


def load_cases(
    processed_root: str | Path,
    dataset: str,
) -> tuple[BenchmarkCase, ...]:
    directory = Path(processed_root) / dataset
    query_path = _query_path(directory)

    if query_path is None:
        raise FileNotFoundError(
            f"No query JSON found for benchmark dataset {dataset!r}."
        )

    payload = json.loads(query_path.read_text(encoding="utf-8"))
    records = payload.get("input_data", payload.get("results"))

    if not isinstance(records, list):
        raise ValueError(
            f"{query_path} must contain input_data or results list."
        )

    return tuple(
        BenchmarkCase(
            dataset=dataset,
            query_id=str(record["query_id"]),
            query=str(record["query"]).strip(),
            reference_answer=_answer_text(record["gt_answer"]),
            metadata={
                key: value
                for key, value in record.items()
                if key
                not in {"query_id", "query", "gt_answer"}
            },
        )
        for record in records
    )


def iter_corpus(
    processed_root: str | Path,
    dataset: str,
) -> Iterator[dict]:
    path = Path(processed_root) / dataset / "corpus.jsonl"

    if not path.is_file():
        raise FileNotFoundError(
            f"No corpus.jsonl found for benchmark dataset {dataset!r}."
        )

    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            doc_id = str(
                record.get("doc_id", record.get("_id", ""))
            ).strip()
            text = str(record.get("text", "")).strip()
            if not doc_id:
                raise ValueError(
                    f"Invalid corpus record at {path}:{line_number}."
                )
            # Some official BEIR corpora contain empty documents. They have no
            # searchable content, so omitting them preserves retrieval meaning
            # while allowing the rest of the published corpus to be indexed.
            if not text:
                continue
            yield {
                "doc_id": doc_id,
                "title": str(record.get("title") or doc_id).strip(),
                "text": text,
            }


def _query_path(directory: Path) -> Path | None:
    if not directory.is_dir():
        return None

    candidates = sorted(directory.glob("*_queries.json"))
    return candidates[0] if candidates else None


def _answer_text(answer) -> str:
    if isinstance(answer, str):
        value = answer.strip()
    elif isinstance(answer, list):
        value = "\n".join(str(item).strip() for item in answer)
    else:
        value = str(answer).strip()

    if not value:
        raise ValueError("Benchmark reference answer cannot be empty.")
    return value

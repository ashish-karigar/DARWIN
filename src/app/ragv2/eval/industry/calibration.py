"""Builds a deterministic, stratified 50-case human review packet.

Overview:
    Human calibration is intentionally separate from automated judges. The
    selector round-robins across datasets and answer outcomes, then writes the
    same frozen examples to JSON, CSV, and a readable Markdown worksheet. The
    reviewer fills the blank rating columns without re-running DARWIN.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import defaultdict, deque
from pathlib import Path

from app.ragv2.eval.industry.checkpoint import BenchmarkCheckpoint
from app.ragv2.eval.industry.config import settings
from app.ragv2.eval.industry.contracts import BenchmarkSample
from app.ragv2.eval.industry.exporters import (
    write_ragas_jsonl,
    write_ragchecker,
)


def load_run_samples(run_root: str | Path) -> tuple[BenchmarkSample, ...]:
    samples = []
    for checkpoint_path in sorted(Path(run_root).glob("*/samples.jsonl")):
        samples.extend(BenchmarkCheckpoint(checkpoint_path).load())
    return tuple(samples)


def stratified_sample(
    samples: tuple[BenchmarkSample, ...],
    size: int = 50,
) -> tuple[BenchmarkSample, ...]:
    if size < 1:
        raise ValueError("Calibration sample size must be positive.")
    if len(samples) < size:
        raise ValueError(
            f"Need at least {size} completed samples; found {len(samples)}."
        )

    strata: dict[tuple[str, bool, bool], list[BenchmarkSample]] = defaultdict(list)
    for sample in samples:
        strata[(sample.dataset, sample.grounded, sample.abstained)].append(sample)

    queues = []
    for key in sorted(strata):
        ordered = sorted(
            strata[key],
            key=lambda item: hashlib.sha256(
                f"{item.dataset}:{item.query_id}".encode()
            ).hexdigest(),
        )
        queues.append(deque(ordered))

    selected = []
    while queues and len(selected) < size:
        remaining = []
        for queue in queues:
            if queue and len(selected) < size:
                selected.append(queue.popleft())
            if queue:
                remaining.append(queue)
        queues = remaining
    return tuple(selected)


def write_review_packet(
    samples: tuple[BenchmarkSample, ...],
    output_directory: str | Path,
) -> tuple[Path, Path, Path]:
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    json_path = destination / "human_review_50.json"
    csv_path = destination / "human_review_50.csv"
    markdown_path = destination / "human_review_50.md"

    write_ragchecker(
        samples,
        destination / "ragchecker_input.json",
    )
    write_ragas_jsonl(
        samples,
        destination / "ragas_input.jsonl",
    )

    records = [_review_record(index, sample) for index, sample in enumerate(samples, 1)]
    json_path.write_text(
        json.dumps(records, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)

    lines = [
        "# DARWIN human calibration sample",
        "",
        "Rate correctness, completeness, faithfulness, and retrieval relevance from 1–5. Mark `acceptable` as yes/no and add concise notes.",
        "",
        "| # | Dataset | Question | Reference | DARWIN response | Sources | Evidence used | Correct | Complete | Faithful | Retrieval | Acceptable | Notes |",
        "|---:|---|---|---|---|---|---|:---:|:---:|:---:|:---:|:---:|---|",
    ]
    for record in records:
        lines.append(
            "| {review_id} | {dataset} | {question} | {reference_answer} | {response} | {sources} | {evidence_used} |  |  |  |  |  |  |".format(
                **{key: _markdown_cell(value) for key, value in record.items()}
            )
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, csv_path, markdown_path


def _review_record(index: int, sample: BenchmarkSample) -> dict:
    sources = "; ".join(
        f"{context.title or context.doc_id}"
        + (f" p.{context.page_number}" if context.page_number else "")
        for context in sample.retrieved_contexts
    )
    evidence = "\n\n".join(
        f"[{context.title or context.doc_id}] {context.text}"
        for context in sample.retrieved_contexts
    )
    return {
        "review_id": index,
        "dataset": sample.dataset,
        "query_id": sample.query_id,
        "question": sample.query,
        "reference_answer": sample.reference_answer,
        "response": sample.response,
        "sources": sources,
        "evidence_used": evidence or "NO FINAL EVIDENCE",
        "grounded_by_darwin": sample.grounded,
        "abstained_by_darwin": sample.abstained,
        "correctness_1_to_5": "",
        "completeness_1_to_5": "",
        "faithfulness_1_to_5": "",
        "retrieval_relevance_1_to_5": "",
        "acceptable_yes_no": "",
        "reviewer_notes": "",
    }


def _markdown_cell(value) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the 50-case human review packet.")
    parser.add_argument("--size", type=int, default=settings.calibration_sample_size)
    parser.add_argument("--run-root", type=Path, default=settings.run_root)
    parser.add_argument("--output", type=Path, default=settings.report_root / "human_calibration")
    arguments = parser.parse_args()

    selected = stratified_sample(load_run_samples(arguments.run_root), arguments.size)
    for artifact in write_review_packet(selected, arguments.output):
        print(f"Artifact: {artifact}")


if __name__ == "__main__":
    main()

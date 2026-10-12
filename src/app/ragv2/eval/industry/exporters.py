"""Transforms DARWIN responses into evaluator-neutral benchmark artifacts.

Overview:
    ``sample_from_response`` captures the exact final context DARWIN used,
    rather than re-running retrieval later. The writer functions then expose
    the same sample set in RAGChecker JSON, RAGAS JSONL, and analyst-friendly
    CSV without invoking any external judge.
"""

import csv
import json
from collections.abc import Sequence
from pathlib import Path

from app.ragv2.eval.industry.contracts import (
    BenchmarkCase,
    BenchmarkSample,
    RetrievedContext,
)
from app.ragv2.service import RagResponse


def sample_from_response(
    case: BenchmarkCase,
    response: RagResponse,
) -> BenchmarkSample:
    context = response.final_context or response.retrieval.context

    retrieved_contexts = tuple(
        RetrievedContext(
            doc_id=item.document_id,
            text=item.text,
            title=item.document_title,
            source_uri=item.source_uri,
            page_number=item.page_number,
            relevance_score=item.relevance_score,
        )
        for item in context.items
    )

    return BenchmarkSample(
        dataset=case.dataset,
        query_id=case.query_id,
        query=case.query,
        reference_answer=case.reference_answer,
        response=response.answer.answer,
        retrieved_contexts=retrieved_contexts,
        grounded=response.answer.is_grounded,
        abstained=response.answer.abstained,
        latency_seconds=response.retrieval.timings.total_seconds,
        route_history=response.route_history,
        metadata={
            **case.metadata,
            "trace_id": response.trace_id,
            "retrieval_attempts": response.retrieval_attempts,
            "web_used": response.web_used,
            "model_calls": [
                event.as_dict() for event in response.model_calls
            ],
        },
    )


def write_ragchecker(
    samples: Sequence[BenchmarkSample],
    path: str | Path,
) -> Path:
    destination = _prepare_destination(path)
    payload = {
        "results": [sample.as_ragchecker() for sample in samples]
    }
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return destination


def write_ragas_jsonl(
    samples: Sequence[BenchmarkSample],
    path: str | Path,
) -> Path:
    destination = _prepare_destination(path)
    with destination.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(
                json.dumps(sample.as_ragas(), ensure_ascii=False)
                + "\n"
            )
    return destination


def write_samples_jsonl(
    samples: Sequence[BenchmarkSample],
    path: str | Path,
) -> Path:
    """Writes the lossless DARWIN representation used for resume/reports."""

    destination = _prepare_destination(path)
    with destination.open("w", encoding="utf-8") as handle:
        for sample in samples:
            handle.write(sample.model_dump_json() + "\n")
    return destination


def write_samples_csv(
    samples: Sequence[BenchmarkSample],
    path: str | Path,
) -> Path:
    destination = _prepare_destination(path)
    fields = (
        "dataset",
        "query_id",
        "query",
        "reference_answer",
        "response",
        "context_count",
        "grounded",
        "abstained",
        "latency_seconds",
        "route_history",
    )

    with destination.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sample in samples:
            writer.writerow(
                {
                    "dataset": sample.dataset,
                    "query_id": sample.query_id,
                    "query": sample.query,
                    "reference_answer": sample.reference_answer,
                    "response": sample.response,
                    "context_count": len(sample.retrieved_contexts),
                    "grounded": sample.grounded,
                    "abstained": sample.abstained,
                    "latency_seconds": sample.latency_seconds,
                    "route_history": " -> ".join(
                        sample.route_history
                    ),
                }
            )
    return destination


def _prepare_destination(path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination

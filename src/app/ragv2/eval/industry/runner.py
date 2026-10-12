"""Resumable runner for DARWIN over RAGChecker benchmark domains.

Overview:
    The runner builds or resumes an isolated dataset index, skips checkpointed
    questions, stops before the configured Groq daily reserve is consumed,
    and writes evaluator-neutral artifacts after every invocation. It never
    performs external judging itself, so expensive judge calls remain a
    separate, inspectable phase.
"""

import argparse
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.llm.usage import GroqUsageStore
from app.ragv2.eval.industry.checkpoint import BenchmarkCheckpoint
from app.ragv2.eval.industry.config import settings
from app.ragv2.eval.industry.contracts import (
    BenchmarkCase,
    BenchmarkSample,
)
from app.ragv2.eval.industry.datasets import load_cases
from app.ragv2.eval.industry.exporters import (
    sample_from_response,
    write_ragas_jsonl,
    write_ragchecker,
    write_samples_csv,
)
from app.ragv2.eval.industry.indexing import ensure_dataset_index
from app.ragv2.service import RagService


@dataclass(frozen=True, slots=True)
class BenchmarkRunReport:
    dataset: str
    available_cases: int
    completed_cases: int
    executed_cases: int
    stopped_for_daily_budget: bool
    checkpoint_path: Path


class IndustryBenchmarkRunner:
    def __init__(
        self,
        service,
        checkpoint: BenchmarkCheckpoint,
        *,
        usage_store: GroqUsageStore | None = None,
        daily_token_reserve: int = settings.daily_token_reserve,
    ):
        self.service = service
        self.checkpoint = checkpoint
        self.usage_store = usage_store or GroqUsageStore()
        self.daily_token_reserve = daily_token_reserve

    def run(
        self,
        dataset: str,
        cases: Sequence[BenchmarkCase],
        *,
        limit: int | None = None,
        progress: bool = False,
    ) -> BenchmarkRunReport:
        completed = self.checkpoint.completed_ids()
        pending = [case for case in cases if case.query_id not in completed]
        if limit is not None:
            pending = pending[:limit]

        executed = 0
        stopped_for_budget = False

        for case in pending:
            remaining = self.usage_store.today().remaining_tokens
            if remaining <= self.daily_token_reserve:
                stopped_for_budget = True
                break

            response = self.service.ask(
                case.query,
                allow_web_search=False,
                trace_name=f"industry-{dataset}-{case.query_id}",
            )
            sample = sample_from_response(case, response)
            self.checkpoint.append(sample)
            completed.add(case.query_id)
            executed += 1

            if progress:
                print(
                    f"[{len(completed)}/{len(cases)}] "
                    f"{case.query_id}: grounded={sample.grounded}, "
                    f"abstained={sample.abstained}, "
                    f"retrieval={sample.latency_seconds:.2f}s"
                )

        return BenchmarkRunReport(
            dataset=dataset,
            available_cases=len(cases),
            completed_cases=len(completed),
            executed_cases=executed,
            stopped_for_daily_budget=stopped_for_budget,
            checkpoint_path=self.checkpoint.path,
        )


def export_checkpoint(
    checkpoint: BenchmarkCheckpoint,
    output_directory: Path,
) -> tuple[Path, Path, Path]:
    samples = checkpoint.load()
    return (
        write_ragchecker(
            samples,
            output_directory / "ragchecker_input.json",
        ),
        write_ragas_jsonl(
            samples,
            output_directory / "ragas_input.jsonl",
        ),
        write_samples_csv(
            samples,
            output_directory / "samples.csv",
        ),
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run DARWIN over one processed RAGChecker domain.",
    )
    parser.add_argument("dataset")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--progress", action="store_true")
    parser.add_argument(
        "--daily-token-reserve",
        type=int,
        default=settings.daily_token_reserve,
    )
    arguments = parser.parse_args()

    cases = load_cases(settings.processed_root, arguments.dataset)
    index = ensure_dataset_index(
        arguments.dataset,
        progress=arguments.progress,
    )
    run_directory = settings.run_root / arguments.dataset
    checkpoint = BenchmarkCheckpoint(run_directory / "samples.jsonl")
    service = RagService(
        rag_settings=index.rag_settings,
        trace_thread_id=f"industry-{arguments.dataset}",
    )
    runner = IndustryBenchmarkRunner(
        service,
        checkpoint,
        daily_token_reserve=arguments.daily_token_reserve,
    )
    report = runner.run(
        arguments.dataset,
        cases,
        limit=arguments.limit,
        progress=arguments.progress,
    )
    artifacts = export_checkpoint(checkpoint, run_directory)

    print(f"Dataset: {report.dataset}")
    print(
        f"Cases: {report.completed_cases}/{report.available_cases} "
        f"({report.executed_cases} executed now)"
    )
    print(f"Stopped for daily budget: {report.stopped_for_daily_budget}")
    for artifact in artifacts:
        print(f"Artifact: {artifact}")


if __name__ == "__main__":
    main()

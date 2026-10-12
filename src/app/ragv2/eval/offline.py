import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from time import perf_counter

from app.ragv2.eval.datasets import EvaluationDataset, load_dataset
from app.ragv2.eval.evaluate import DEFAULT_DATASET
from app.ragv2.eval.metrics import percentage, percentile, source_matches
from app.ragv2.retrieve.retrieval.hybrid import HybridRetriever
from app.ragv2.retrieve.retrieval.reranker import CrossEncoderReranker


@dataclass(frozen=True, slots=True)
class CandidateCaseResult:
    case_id: str
    retrieval_rank: int | None
    top_score: float | None
    latency_seconds: float
    error: str | None = None


@dataclass(frozen=True, slots=True)
class CandidateEvaluationReport:
    dataset: str
    answerable_case_count: int
    successful_cases: int
    hit_at_1_percent: float
    hit_at_5_percent: float
    mean_reciprocal_rank: float
    average_latency_seconds: float
    p95_latency_seconds: float
    cases: tuple[CandidateCaseResult, ...]

    def to_dict(self) -> dict:
        return asdict(self)


class CandidateEvaluator:
    """Measures local hybrid retrieval and reranking without an LLM."""

    def __init__(
        self,
        hybrid_retriever: HybridRetriever | None = None,
        reranker: CrossEncoderReranker | None = None,
    ):
        self.hybrid_retriever = hybrid_retriever or HybridRetriever()
        self.reranker = reranker or CrossEncoderReranker()

    def evaluate(
        self,
        dataset: EvaluationDataset,
    ) -> CandidateEvaluationReport:
        answerable = tuple(
            case for case in dataset.cases if case.should_answer
        )
        results = tuple(
            self._run_case(case)
            for case in answerable
        )
        successful = tuple(
            result for result in results if result.error is None
        )
        ranks = tuple(
            result.retrieval_rank
            for result in successful
            if result.retrieval_rank is not None
        )
        latencies = tuple(
            result.latency_seconds for result in successful
        )

        return CandidateEvaluationReport(
            dataset=dataset.name,
            answerable_case_count=len(answerable),
            successful_cases=len(successful),
            hit_at_1_percent=percentage(
                sum(rank == 1 for rank in ranks),
                len(answerable),
            ),
            hit_at_5_percent=percentage(
                sum(rank <= 5 for rank in ranks),
                len(answerable),
            ),
            mean_reciprocal_rank=(
                round(
                    sum(1 / rank for rank in ranks)
                    / len(answerable),
                    4,
                )
                if answerable
                else 0.0
            ),
            average_latency_seconds=(
                round(sum(latencies) / len(latencies), 4)
                if latencies
                else 0.0
            ),
            p95_latency_seconds=percentile(latencies, 0.95),
            cases=results,
        )

    def _run_case(self, case) -> CandidateCaseResult:
        started_at = perf_counter()

        try:
            candidates = self.hybrid_retriever.search(
                case.question
            )
            reranked = self.reranker.rerank(
                case.question,
                candidates,
            )
            rank = next(
                (
                    index
                    for index, hit in enumerate(reranked, start=1)
                    if source_matches(
                        hit.chunk.source_uri,
                        case.expected_source_suffixes,
                    )
                ),
                None,
            )

            return CandidateCaseResult(
                case_id=case.case_id,
                retrieval_rank=rank,
                top_score=(
                    reranked[0].score if reranked else None
                ),
                latency_seconds=round(
                    perf_counter() - started_at,
                    4,
                ),
            )
        except Exception as error:
            return CandidateCaseResult(
                case_id=case.case_id,
                retrieval_rank=None,
                top_score=None,
                latency_seconds=round(
                    perf_counter() - started_at,
                    4,
                ),
                error=type(error).__name__,
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET,
    )
    arguments = parser.parse_args()
    report = CandidateEvaluator().evaluate(
        load_dataset(arguments.dataset)
    )
    print(json.dumps(report.to_dict(), indent=2))


if __name__ == "__main__":
    main()

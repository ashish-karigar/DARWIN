import json
import argparse
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from time import monotonic

from app.agents.knowledge_agent import run_knowledge_agent
from app.rag.retriever import DEFAULT_SCORE_THRESHOLD, retrieve


CASES_PATH = Path("data/evaluation/rag_cases.json")
REPORT_PATH = Path("data/evaluation/rag_latest.json")


def _contains_terms(text: str, terms: list[str]) -> bool:
    def canonical(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value).casefold()
        return re.sub(r"[^a-z0-9]+", "", normalized)

    normalized = canonical(text)
    return all(canonical(term) in normalized for term in terms)


def evaluate_retrieval(run_answer_evaluation: bool = True) -> dict:
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = []

    for case in cases:
        started = monotonic()
        retrieved = retrieve(
            case["query"],
            "darwin_knowledge",
            limit=3,
        )
        retrieval_seconds = monotonic() - started

        relevant_ranks = [
            rank
            for rank, result in enumerate(retrieved, start=1)
            if case["expected_terms"]
            and _contains_terms(result.content, case["expected_terms"])
        ]

        if case["expected_no_answer"]:
            retrieval_pass = len(retrieved) == 0
            reciprocal_rank = 1.0 if retrieval_pass else 0.0
            first_relevant_rank = None
        else:
            retrieval_pass = bool(relevant_ranks)
            reciprocal_rank = 1.0 / relevant_ranks[0] if relevant_ranks else 0.0
            first_relevant_rank = relevant_ranks[0] if relevant_ranks else None

        answer = None
        answer_pass = None
        answer_seconds = None
        if run_answer_evaluation:
            answer_started = monotonic()
            answer = run_knowledge_agent(case["query"])
            answer_seconds = monotonic() - answer_started
            if case["expected_no_answer"]:
                answer_pass = any(
                    phrase in answer.casefold()
                    for phrase in (
                        "insufficient",
                        "not found",
                        "does not contain",
                        "don't have",
                        "do not have",
                    )
                )
            else:
                answer_pass = _contains_terms(answer, case["expected_terms"])

        results.append(
            {
                "id": case["id"],
                "retrieval_pass": retrieval_pass,
                "reciprocal_rank": round(reciprocal_rank, 3),
                "first_relevant_rank": first_relevant_rank,
                "returned_count": len(retrieved),
                "top_score": retrieved[0].score if retrieved else None,
                "retrieved": [result.to_dict() for result in retrieved],
                "retrieval_seconds": round(retrieval_seconds, 3),
                "answer_pass": answer_pass,
                "answer_seconds": round(answer_seconds, 3)
                if answer_seconds is not None
                else None,
                "answer": answer,
            }
        )

    retrieval_passes = [item["retrieval_pass"] for item in results]
    answerable = [
        item for item, case in zip(results, cases) if not case["expected_no_answer"]
    ]
    unanswerable = [
        item for item, case in zip(results, cases) if case["expected_no_answer"]
    ]
    answer_passes = [
        item["answer_pass"] for item in results if item["answer_pass"] is not None
    ]
    report = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": str(CASES_PATH),
        "case_count": len(results),
        "score_threshold": DEFAULT_SCORE_THRESHOLD,
        "retrieval_accuracy_percent": round(100 * mean(retrieval_passes), 1),
        "hit_at_1_percent": round(
            100 * mean(item["first_relevant_rank"] == 1 for item in answerable), 1
        ),
        "hit_at_3_percent": round(
            100 * mean(item["first_relevant_rank"] is not None for item in answerable),
            1,
        ),
        "no_answer_rejection_percent": round(
            100 * mean(item["retrieval_pass"] for item in unanswerable), 1
        )
        if unanswerable
        else None,
        "mean_reciprocal_rank": round(
            mean(item["reciprocal_rank"] for item in results), 3
        ),
        "average_retrieval_seconds": round(
            mean(item["retrieval_seconds"] for item in results), 3
        ),
        "answer_required_term_accuracy_percent": round(100 * mean(answer_passes), 1)
        if answer_passes
        else None,
        "results": results,
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate DARWIN RAG quality.")
    parser.add_argument(
        "--retrieval-only",
        action="store_true",
        help="Skip external LLM answer evaluation.",
    )
    args = parser.parse_args()
    report = evaluate_retrieval(run_answer_evaluation=not args.retrieval_only)
    summary = {key: value for key, value in report.items() if key != "results"}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

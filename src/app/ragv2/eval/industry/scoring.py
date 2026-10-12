"""Independent RAGChecker and RAGAS judge adapters.

Overview:
    DARWIN first records immutable benchmark samples. This module judges a
    selected shard afterwards, so an evaluator failure or rate limit cannot
    corrupt the product run. Groq is the primary judge; Ollama can score the
    same shard for agreement calibration. Heavy evaluator imports are delayed
    so Core RAG v2 never depends on the benchmark environment at runtime.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any

from dotenv import load_dotenv

from app.llm.usage import GroqUsageCallback, GroqUsageStore
from app.ragv2.eval.industry.config import settings


@dataclass(frozen=True, slots=True)
class JudgeBackend:
    name: str
    model: str
    api_base: str | None = None


def judge_backend(name: str) -> JudgeBackend:
    normalized = name.strip().casefold()
    if normalized == "groq":
        return JudgeBackend(
            name="groq",
            model=os.getenv(
                "DARWIN_INDUSTRY_GROQ_JUDGE",
                "groq/openai/gpt-oss-120b",
            ),
        )
    if normalized == "ollama":
        return JudgeBackend(
            name="ollama",
            model=os.getenv(
                "DARWIN_INDUSTRY_LOCAL_JUDGE",
                "ollama/qwen3:8b",
            ),
            api_base=os.getenv(
                "OLLAMA_BASE_URL",
                "http://127.0.0.1:11434",
            ),
        )
    raise ValueError("Judge must be either 'groq' or 'ollama'.")


def run_ragchecker(
    input_path: str | Path,
    output_path: str | Path,
    *,
    judge: str,
    offset: int = 0,
    limit: int | None = None,
    estimated_tokens_per_case: int = 8_000,
) -> dict[str, Any]:
    """Scores one resumable shard with the official RAGChecker package."""

    from ragchecker import RAGChecker, RAGResults

    backend = judge_backend(judge)
    source_payload = json.loads(Path(input_path).read_text(encoding="utf-8"))
    records = source_payload["results"]
    selected = records[offset:offset + limit if limit else None]
    if not selected:
        raise ValueError("The selected RAGChecker shard is empty.")
    _prepare_provider_budget(
        backend,
        len(selected),
        estimated_tokens_per_case,
    )

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = destination.with_suffix(".checkpoint.json")

    if checkpoint.is_file():
        results = RAGResults.from_json(checkpoint.read_text(encoding="utf-8"))
    else:
        results = RAGResults.from_json(
            json.dumps({"results": selected}, ensure_ascii=False)
        )

    evaluator = RAGChecker(
        extractor_name=backend.model,
        checker_name=backend.model,
        extractor_api_base=backend.api_base,
        checker_api_base=backend.api_base,
        batch_size_extractor=1,
        batch_size_checker=1,
        joint_check=True,
        custom_llm_api_func=_ragchecker_fail_fast_client(backend),
    )
    evaluator.evaluate(results, save_path=str(checkpoint))
    payload = json.loads(results.to_json())
    payload["judge"] = backend.name
    payload["model"] = backend.model
    payload["source"] = str(input_path)
    payload["offset"] = offset
    payload["limit"] = len(selected)
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    _write_ragchecker_summary(payload, destination)
    return payload


def _ragchecker_fail_fast_client(backend: JudgeBackend):
    """Returns a single-attempt LiteLLM client for RAGChecker.

    RAGChecker's upstream default retries failed batch responses forever. That
    is unsafe for a quota-bounded benchmark: a daily-limit error can otherwise
    sleep and retry indefinitely. Keeping the hook here preserves RAGChecker's
    prompts and metrics while making provider exhaustion checkpoint-and-exit.
    """

    def invoke(prompts: list[str]) -> list[str]:
        import litellm

        responses = []
        for prompt in prompts:
            options = {
                "model": backend.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0,
                "max_tokens": 1_000,
                "num_retries": 0,
            }
            if backend.api_base:
                options["api_base"] = backend.api_base
            response = litellm.completion(**options)
            content = response.choices[0].message.content
            if not content:
                raise RuntimeError(
                    f"{backend.name} returned an empty RAGChecker response."
                )
            responses.append(content)
        return responses

    return invoke


def run_ragas(
    input_path: str | Path,
    output_path: str | Path,
    *,
    judge: str,
    offset: int = 0,
    limit: int | None = None,
    estimated_tokens_per_case: int = 6_000,
) -> dict[str, Any]:
    """Scores one shard with four standard RAGAS metrics."""

    from langchain_community.embeddings import HuggingFaceEmbeddings
    from langchain_openai import ChatOpenAI
    from ragas import EvaluationDataset, evaluate
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithReference,
        LLMContextRecall,
        ResponseRelevancy,
    )

    backend = judge_backend(judge)
    records = _read_jsonl(input_path)
    selected = records[offset:offset + limit if limit else None]
    if not selected:
        raise ValueError("The selected RAGAS shard is empty.")
    usage_store = _prepare_provider_budget(
        backend,
        len(selected),
        estimated_tokens_per_case,
    )

    if backend.name == "groq":
        model_name = backend.model.removeprefix("groq/")
        api_key = os.environ["GROQ_API_KEY"]
        base_url = "https://api.groq.com/openai/v1"
    else:
        model_name = backend.model.removeprefix("ollama/")
        api_key = "ollama"
        base_url = backend.api_base.rstrip("/") + "/v1"

    language_model = LangchainLLMWrapper(
        ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0,
            max_retries=2,
            callbacks=(
                [GroqUsageCallback(usage_store)]
                if usage_store is not None
                else None
            ),
        )
    )
    embeddings = LangchainEmbeddingsWrapper(
        HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
        )
    )
    metrics = [
        Faithfulness(llm=language_model),
        ResponseRelevancy(
            llm=language_model,
            embeddings=embeddings,
            strictness=1,
        ),
        LLMContextPrecisionWithReference(llm=language_model),
        LLMContextRecall(llm=language_model),
    ]
    result = evaluate(
        EvaluationDataset.from_list(selected),
        metrics=metrics,
        llm=language_model,
        embeddings=embeddings,
        batch_size=1,
        raise_exceptions=False,
        show_progress=True,
    )
    rows = result.to_pandas().to_dict(orient="records")
    metric_names = tuple(metric.name for metric in metrics)
    summary = {
        name: _safe_mean(row.get(name) for row in rows)
        for name in metric_names
    }
    payload = {
        "judge": backend.name,
        "model": backend.model,
        "source": str(input_path),
        "offset": offset,
        "limit": len(selected),
        "summary": summary,
        "results": rows,
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    _write_flat_summary(payload, destination, title="RAGAS")
    return payload


def compare_judges(
    primary_path: str | Path,
    local_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    """Measures aggregate judge agreement without hiding disagreements."""

    primary = json.loads(Path(primary_path).read_text(encoding="utf-8"))
    local = json.loads(Path(local_path).read_text(encoding="utf-8"))
    primary_summary = _numeric_summary(primary)
    local_summary = _numeric_summary(local)
    shared = sorted(primary_summary.keys() & local_summary.keys())
    metrics = []
    for name in shared:
        primary_score = primary_summary[name]
        local_score = local_summary[name]
        metrics.append(
            {
                "metric": name,
                "primary": primary_score,
                "local": local_score,
                "absolute_delta": abs(primary_score - local_score),
                "within_0_15": abs(primary_score - local_score) <= 0.15,
            }
        )
    payload = {
        "primary": str(primary_path),
        "local": str(local_path),
        "metrics": metrics,
        "mean_absolute_delta": _safe_mean(
            item["absolute_delta"] for item in metrics
        ),
    }
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_agreement_reports(payload, destination)
    return payload


def merge_score_shards(
    shard_paths: list[str | Path],
    output_path: str | Path,
) -> dict[str, Any]:
    """Merges completed score shards and recomputes weighted summaries."""

    if not shard_paths:
        raise ValueError("At least one score shard is required.")
    shards = [json.loads(Path(path).read_text(encoding="utf-8")) for path in shard_paths]
    seen = set()
    results = []
    for shard in shards:
        for index, record in enumerate(shard.get("results", [])):
            identity = str(record.get("query_id", f"row:{len(results)}:{index}"))
            if identity in seen:
                continue
            seen.add(identity)
            results.append(record)

    if "metrics" in shards[0]:
        group_metrics = shards[0]["metrics"]
        summary = {}
        for group, metrics in group_metrics.items():
            summary[group] = {
                metric: _safe_mean(
                    record.get("metrics", {}).get(metric) for record in results
                )
                for metric in metrics
            }
        payload = {
            "judge": shards[0].get("judge"),
            "model": shards[0].get("model"),
            "shards": [str(path) for path in shard_paths],
            "results": results,
            "metrics": summary,
        }
    else:
        metric_names = tuple((shards[0].get("summary") or {}).keys())
        payload = {
            "judge": shards[0].get("judge"),
            "model": shards[0].get("model"),
            "shards": [str(path) for path in shard_paths],
            "results": results,
            "summary": {
                metric: _safe_mean(record.get(metric) for record in results)
                for metric in metric_names
            },
        }

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    if "metrics" in payload:
        _write_ragchecker_summary(payload, destination)
    else:
        _write_flat_summary(payload, destination, title="RAGAS")
    return payload


def _read_jsonl(path: str | Path) -> list[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def _prepare_provider_budget(
    backend: JudgeBackend,
    case_count: int,
    estimated_tokens_per_case: int,
) -> GroqUsageStore | None:
    if backend.name != "groq":
        return None
    usage_store = GroqUsageStore()
    remaining = usage_store.today().remaining_tokens
    estimated = case_count * estimated_tokens_per_case
    usable = max(0, remaining - settings.daily_token_reserve)
    if estimated > usable:
        raise RuntimeError(
            "Judge shard is too large for DARWIN's tracked Groq budget: "
            f"estimated {estimated:,} tokens but {usable:,} are available "
            "after reserve. Reduce --limit and resume with --offset."
        )
    _install_litellm_usage_tracking(usage_store)
    return usage_store


def _install_litellm_usage_tracking(usage_store: GroqUsageStore) -> None:
    import litellm

    def record_usage(kwargs, completion_response, start_time, end_time):
        usage = getattr(completion_response, "usage", None)
        if usage is None:
            return
        usage_store.record(
            model="openai/gpt-oss-120b",
            input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
            total_tokens=int(getattr(usage, "total_tokens", 0) or 0),
        )

    callbacks = list(getattr(litellm, "success_callback", []) or [])
    callbacks.append(record_usage)
    litellm.success_callback = callbacks


def _safe_mean(values) -> float | None:
    numbers = [float(value) for value in values if value is not None]
    return round(mean(numbers), 4) if numbers else None


def _numeric_summary(payload: dict[str, Any]) -> dict[str, float]:
    summary = payload.get("summary") or payload.get("metrics") or {}
    flattened = {}
    for name, value in summary.items():
        if isinstance(value, dict):
            for child_name, child_value in value.items():
                if isinstance(child_value, (int, float)):
                    flattened[f"{name}.{child_name}"] = float(child_value)
        elif isinstance(value, (int, float)):
            flattened[name] = float(value)
    return flattened


def _write_ragchecker_summary(payload: dict[str, Any], path: Path) -> None:
    rows = [
        (f"{group}.{metric}", value)
        for group, metrics in payload.get("metrics", {}).items()
        for metric, value in metrics.items()
    ]
    _write_metric_rows(rows, path, "RAGChecker")


def _write_flat_summary(
    payload: dict[str, Any],
    path: Path,
    *,
    title: str,
) -> None:
    _write_metric_rows(list(payload["summary"].items()), path, title)


def _write_metric_rows(rows, path: Path, title: str) -> None:
    csv_path = path.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("metric", "score"))
        writer.writerows(rows)
    markdown = [f"# {title} summary", "", "| Metric | Score |", "|---|---:|"]
    markdown.extend(f"| {name} | {value} |" for name, value in rows)
    path.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8")


def _write_agreement_reports(payload: dict[str, Any], path: Path) -> None:
    rows = payload["metrics"]
    csv_path = path.with_suffix(".csv")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys() if rows else ("metric",))
        writer.writeheader()
        writer.writerows(rows)
    markdown = [
        "# Judge agreement",
        "",
        "| Metric | Groq | Local | Absolute delta | Within 0.15 |",
        "|---|---:|---:|---:|:---:|",
    ]
    markdown.extend(
        "| {metric} | {primary} | {local} | {absolute_delta} | {within_0_15} |".format(**row)
        for row in rows
    )
    path.with_suffix(".md").write_text("\n".join(markdown) + "\n", encoding="utf-8")


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Score frozen DARWIN benchmark samples.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for command in ("ragchecker", "ragas"):
        child = subparsers.add_parser(command)
        child.add_argument("input")
        child.add_argument("output")
        child.add_argument("--judge", choices=("groq", "ollama"), required=True)
        child.add_argument("--offset", type=int, default=0)
        child.add_argument("--limit", type=int, default=None)
        child.add_argument("--estimated-tokens-per-case", type=int, default=None)

    agreement = subparsers.add_parser("agreement")
    agreement.add_argument("primary")
    agreement.add_argument("local")
    agreement.add_argument("output")
    merge = subparsers.add_parser("merge")
    merge.add_argument("output")
    merge.add_argument("shards", nargs="+")
    arguments = parser.parse_args()

    if arguments.command == "ragchecker":
        options = {}
        if arguments.estimated_tokens_per_case is not None:
            options["estimated_tokens_per_case"] = arguments.estimated_tokens_per_case
        run_ragchecker(
            arguments.input,
            arguments.output,
            judge=arguments.judge,
            offset=arguments.offset,
            limit=arguments.limit,
            **options,
        )
    elif arguments.command == "ragas":
        options = {}
        if arguments.estimated_tokens_per_case is not None:
            options["estimated_tokens_per_case"] = arguments.estimated_tokens_per_case
        run_ragas(
            arguments.input,
            arguments.output,
            judge=arguments.judge,
            offset=arguments.offset,
            limit=arguments.limit,
            **options,
        )
    elif arguments.command == "agreement":
        compare_judges(arguments.primary, arguments.local, arguments.output)
    else:
        merge_score_shards(arguments.shards, arguments.output)


if __name__ == "__main__":
    main()

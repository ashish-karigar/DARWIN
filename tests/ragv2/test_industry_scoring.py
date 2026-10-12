import json
import sys
from types import SimpleNamespace

from app.ragv2.eval.industry.scoring import (
    _ragchecker_fail_fast_client,
    compare_judges,
    judge_backend,
    merge_score_shards,
)


def test_resolves_supported_judges():
    assert judge_backend("groq").model.startswith("groq/")
    assert judge_backend("ollama").api_base


def test_ragchecker_client_disables_provider_retries(monkeypatch):
    calls = []

    class Message:
        content = "scored"

    class Choice:
        message = Message()

    class Response:
        choices = [Choice()]

    def completion(**kwargs):
        calls.append(kwargs)
        return Response()

    monkeypatch.setitem(
        sys.modules,
        "litellm",
        SimpleNamespace(completion=completion),
    )
    client = _ragchecker_fail_fast_client(judge_backend("groq"))

    assert client(["judge this"]) == ["scored"]
    assert calls[0]["num_retries"] == 0


def test_compares_judge_metric_summaries(tmp_path):
    primary = tmp_path / "primary.json"
    local = tmp_path / "local.json"
    output = tmp_path / "agreement.json"
    primary.write_text(json.dumps({"summary": {"faithfulness": 0.9}}))
    local.write_text(json.dumps({"summary": {"faithfulness": 0.8}}))

    result = compare_judges(primary, local, output)

    assert result["mean_absolute_delta"] == 0.1
    assert result["metrics"][0]["within_0_15"] is True
    assert output.with_suffix(".csv").is_file()
    assert output.with_suffix(".md").is_file()


def test_merges_ragas_shards_with_weighted_case_mean(tmp_path):
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    output = tmp_path / "merged.json"
    first.write_text(
        json.dumps(
            {
                "summary": {"faithfulness": 1.0},
                "results": [{"query_id": "one", "faithfulness": 1.0}],
            }
        )
    )
    second.write_text(
        json.dumps(
            {
                "summary": {"faithfulness": 0.0},
                "results": [
                    {"query_id": "two", "faithfulness": 0.0},
                    {"query_id": "three", "faithfulness": 0.0},
                ],
            }
        )
    )

    result = merge_score_shards([first, second], output)

    assert result["summary"]["faithfulness"] == 0.3333

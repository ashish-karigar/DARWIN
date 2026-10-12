from datetime import UTC, datetime

from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, LLMResult

from app.llm.usage import GroqUsageCallback, GroqUsageStore


def test_persists_and_aggregates_daily_usage(tmp_path):
    store = GroqUsageStore(
        tmp_path / "usage.sqlite3",
        daily_limit_tokens=200_000,
    )
    now = datetime(2026, 9, 12, 12, tzinfo=UTC)

    store.record(
        model="openai/gpt-oss-120b",
        input_tokens=800,
        output_tokens=200,
        total_tokens=1_000,
        occurred_at=now,
    )
    store.record(
        model="openai/gpt-oss-120b",
        input_tokens=400,
        output_tokens=100,
        total_tokens=500,
        occurred_at=now,
    )

    usage = store.today(model="openai/gpt-oss-120b", now=now)

    assert usage.used_tokens == 1_500
    assert usage.input_tokens == 1_200
    assert usage.output_tokens == 300
    assert usage.remaining_tokens == 198_500
    assert usage.request_count == 2


def test_callback_reads_langchain_message_usage(tmp_path):
    store = GroqUsageStore(tmp_path / "usage.sqlite3")
    callback = GroqUsageCallback(store)
    result = LLMResult(
        generations=[
            [
                ChatGeneration(
                    message=AIMessage(
                        content="answer",
                        usage_metadata={
                            "input_tokens": 120,
                            "output_tokens": 30,
                            "total_tokens": 150,
                        },
                        response_metadata={
                            "model_name": "openai/gpt-oss-120b"
                        },
                    )
                )
            ]
        ]
    )

    callback.on_llm_end(result)
    usage = store.today(model="openai/gpt-oss-120b")

    assert usage.used_tokens == 150
    assert usage.request_count == 1

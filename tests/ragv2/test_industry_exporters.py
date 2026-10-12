import json
from types import SimpleNamespace

from app.llm.telemetry import ModelCallEvent
from app.ragv2.contracts import (
    ContentType,
    ContextBundle,
    ContextItem,
    GroundedAnswer,
)
from app.ragv2.eval.industry.contracts import BenchmarkCase
from app.ragv2.eval.industry.exporters import (
    sample_from_response,
    write_ragchecker,
    write_ragas_jsonl,
)


def _response():
    item = ContextItem(
        parent_id="parent-1",
        document_id="doc-1",
        document_title="Reference document",
        text="The answer is grounded in this passage.",
        content_type=ContentType.TEXT,
        source_uri="reference.txt",
        page_number=2,
        supporting_chunk_ids=("chunk-1",),
        relevance_score=0.91,
        directly_answers=True,
        expanded_from_parent=False,
    )
    context = ContextBundle(
        query="What is the answer?",
        items=(item,),
        total_tokens=9,
        has_direct_evidence=True,
    )
    answer = GroundedAnswer(
        query="What is the answer?",
        answer="The answer is grounded [S1].",
        citations=(),
        is_grounded=False,
        abstained=False,
    )
    event = ModelCallEvent(
        schema="AnswerDraft",
        provider="groq",
        outcome="success",
        attempt=1,
        elapsed_seconds=0.2,
        used_fallback=False,
    )
    return SimpleNamespace(
        final_context=context,
        retrieval=SimpleNamespace(
            context=context,
            timings=SimpleNamespace(total_seconds=0.4),
        ),
        answer=answer,
        route_history=("retrieve", "generate", "finalize"),
        trace_id="trace-1",
        retrieval_attempts=1,
        web_used=False,
        model_calls=(event,),
    )


def test_response_is_exported_to_both_standard_shapes(tmp_path):
    case = BenchmarkCase(
        dataset="example",
        query_id="q-1",
        query="What is the answer?",
        reference_answer="The answer is grounded.",
    )
    sample = sample_from_response(case, _response())

    ragchecker_path = write_ragchecker(
        (sample,),
        tmp_path / "ragchecker.json",
    )
    ragas_path = write_ragas_jsonl(
        (sample,),
        tmp_path / "ragas.jsonl",
    )

    ragchecker = json.loads(ragchecker_path.read_text())
    ragas = json.loads(ragas_path.read_text().strip())

    record = ragchecker["results"][0]
    assert record["query_id"] == "q-1"
    assert record["gt_answer"] == "The answer is grounded."
    assert record["retrieved_context"] == [
        {
            "doc_id": "doc-1",
            "text": "The answer is grounded in this passage.",
        }
    ]
    assert ragas == {
        "user_input": "What is the answer?",
        "retrieved_contexts": [
            "The answer is grounded in this passage."
        ],
        "response": "The answer is grounded [S1].",
        "reference": "The answer is grounded.",
    }

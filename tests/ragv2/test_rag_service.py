import json

import pytest

from app.ragv2.contracts import (
    Citation,
    EvidenceStatus,
    GroundedAnswer,
    QueryAnalysis,
    QueryStrategy,
)
from app.ragv2.retrieve.retrieve import (
    RetrievalResult,
    RetrievalTimings,
)
from app.ragv2.observability.langsmith import (
    LangSmithObservability,
)
from app.ragv2.service import RagResponse, RagService
from app.ragv2.tools import serialize_response


class FakeGraph:
    def __init__(self, state):
        self.state = state
        self.inputs = []

    def invoke(self, graph_input, config=None):
        self.inputs.append((graph_input, config))
        return self.state


def make_retrieval():
    from app.ragv2.contracts import ContextBundle

    return RetrievalResult(
        query="Question",
        analysis=QueryAnalysis(
            original_query="Question",
            standalone_query="Question",
            strategy=QueryStrategy.DIRECT,
        ),
        traces=(),
        candidates=(),
        reranked_hits=(),
        grades=(),
        context=ContextBundle(
            query="Question",
            items=(),
            total_tokens=0,
            has_direct_evidence=False,
        ),
        unanswered_queries=("Question",),
        timings=RetrievalTimings(0, 0, 0, 0, 0, 0),
    )


def test_service_returns_typed_final_state():
    retrieval = make_retrieval()
    graph = FakeGraph(
        {
            "answer": GroundedAnswer(
                query="Question",
                answer="No reliable evidence.",
                is_grounded=False,
                abstained=True,
            ),
            "evidence_status": EvidenceStatus.IRRELEVANT,
            "retrieval": retrieval,
            "retrieval_attempts": 0,
            "web_used": False,
            "route_history": ("retrieve", "abstain", "finalize"),
        }
    )

    response = RagService(
        graph=graph,
        observability=LangSmithObservability(
            enabled=False,
            api_key=None,
        ),
    ).ask(" Question ")

    assert response.answer.abstained is True
    assert response.retrieval is retrieval
    graph_input, config = graph.inputs[0]

    assert graph_input["question"] == "Question"
    assert config["run_name"] == "question-01"
    assert config["metadata"]["component"] == "ragv2"
    assert config["metadata"]["request_number"] == 1
    assert config["metadata"]["thread_id"].startswith(
        "rag-session-"
    )
    assert response.trace_id is None


def test_service_rejects_empty_question():
    with pytest.raises(ValueError, match="cannot be empty"):
        RagService(graph=FakeGraph({})).ask(" ")


def test_tool_serializer_preserves_grounding_metadata():
    graph = FakeGraph(
        {
            "answer": GroundedAnswer(
                query="Question",
                answer="No reliable evidence.",
                is_grounded=False,
                abstained=True,
            ),
            "evidence_status": EvidenceStatus.IRRELEVANT,
            "retrieval": make_retrieval(),
            "route_history": (),
        }
    )
    response = RagService(graph=graph).ask("Question")
    payload = json.loads(serialize_response(response))

    assert payload["abstained"] is True
    assert payload["grounded"] is False
    assert payload["verified"] is None


def test_batch_groups_named_questions_under_one_thread():
    graph = FakeGraph(
        {
            "answer": GroundedAnswer(
                query="Question",
                answer="No reliable evidence.",
                is_grounded=False,
                abstained=True,
            ),
            "evidence_status": EvidenceStatus.IRRELEVANT,
            "retrieval": make_retrieval(),
            "route_history": (),
        }
    )
    service = RagService(
        graph=graph,
        observability=LangSmithObservability(
            enabled=False,
            api_key=None,
        ),
        trace_thread_id="rag-regression-01",
    )

    responses = service.ask_many(
        ("Question one", "Question two"),
        batch_name="rag-regression",
    )

    assert len(responses) == 2
    configs = [config for _, config in graph.inputs]
    assert [config["run_name"] for config in configs] == [
        "question-01",
        "question-02",
    ]
    assert {
        config["metadata"]["thread_id"]
        for config in configs
    } == {"rag-regression-01"}


def test_batch_trace_outputs_include_summary_and_results():
    response = RagService(
        graph=FakeGraph({}),
        observability=LangSmithObservability(
            enabled=False,
            api_key=None,
        ),
    )
    rag_response = RagResponse(
        answer=GroundedAnswer(
            query="Question",
            answer="Grounded answer [S1].",
            citations=(
                Citation(
                    citation_id="S1",
                    document_id="document-1",
                    document_title="Document",
                    source_uri="/document.pdf",
                    page_number=1,
                    parent_id="section-1",
                ),
            ),
            is_grounded=True,
            abstained=False,
        ),
        evidence_status=EvidenceStatus.SUFFICIENT,
        verification=None,
        retrieval_attempts=0,
        web_used=False,
        route_history=("retrieve", "generate", "finalize"),
        retrieval=make_retrieval(),
    )

    outputs = response._batch_trace_outputs(
        ("Question",),
        (rag_response,),
    )

    assert outputs["summary"] == {
        "question_count": 1,
        "grounded_count": 1,
        "abstained_count": 0,
        "verified_count": 0,
        "provider_failure_count": 0,
        "fallback_used_count": 0,
        "schema_invalid_count": 0,
    }
    assert outputs["results"][0]["question"] == "Question"
    assert outputs["results"][0]["answer"] == (
        "Grounded answer [S1]."
    )

from contextlib import nullcontext

import pytest

from app.ragv2.observability.langsmith import (
    LangSmithConfigurationError,
    LangSmithObservability,
)


def test_tracing_is_disabled_without_opt_in():
    observer = LangSmithObservability(
        enabled=False,
        api_key=None,
    )
    session = observer.start_session(
        allow_web_search=False,
        vector_collection="test-collection",
        thread_id="thread-1",
        request_id="request-1",
        run_name="question-01",
        request_number=1,
    )

    assert session.enabled is False
    assert session.public_trace_id is None
    assert isinstance(observer.tracing_context(session), nullcontext)


def test_enabled_tracing_requires_api_key():
    with pytest.raises(
        LangSmithConfigurationError,
        match="LANGSMITH_API_KEY",
    ):
        LangSmithObservability(
            enabled=True,
            api_key="",
        )


def test_session_exposes_safe_trace_metadata():
    observer = LangSmithObservability(
        enabled=True,
        api_key="test-key",
        project_name="darwin-tests",
    )
    session = observer.start_session(
        allow_web_search=True,
        vector_collection="chunks",
        thread_id="thread-1",
        request_id="request-1",
        run_name="question-01",
        request_number=1,
    )
    config = session.runnable_config()

    assert session.public_trace_id == str(session.run_id)
    assert config["run_name"] == "question-01"
    assert config["tags"] == ["darwin", "ragv2", "request"]
    assert config["metadata"] == {
        "component": "ragv2",
        "thread_id": "thread-1",
        "request_id": "request-1",
        "request_number": 1,
        "allow_web_search": True,
        "vector_collection": "chunks",
    }


def test_darwin_specific_flag_overrides_global_tracing(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("DARWIN_LANGSMITH_TRACING", "false")

    observer = LangSmithObservability(api_key=None)

    assert observer.enabled is False


def test_disabled_batch_context_creates_no_trace():
    observer = LangSmithObservability(
        enabled=False,
        api_key=None,
    )

    with observer.batch_context(
        batch_name="rag-regression",
        thread_id="thread-1",
        questions=("Question one", "Question two"),
    ) as run:
        assert run is None

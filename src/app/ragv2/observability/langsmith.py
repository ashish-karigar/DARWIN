import os
from contextlib import (
    AbstractContextManager,
    contextmanager,
    nullcontext,
)
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from uuid import UUID, uuid4

import langsmith as ls

from app.ragv2.config import environment_flag


class LangSmithConfigurationError(RuntimeError):
    """Raised when tracing is enabled without usable credentials."""


@dataclass(frozen=True, slots=True)
class TraceSession:
    """Carries one request run ID and its LangGraph configuration."""

    run_id: UUID
    enabled: bool
    project_name: str
    tags: tuple[str, ...]
    metadata: dict[str, object]
    run_name: str

    @property
    def public_trace_id(self) -> str | None:
        return str(self.run_id) if self.enabled else None

    def runnable_config(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_name": self.run_name,
            "tags": list(self.tags),
            "metadata": self.metadata,
        }


class LangSmithObservability:
    """Creates selective, grouped LangSmith traces for RAG requests.

    DARWIN_LANGSMITH_TRACING enables only the explicitly wrapped RAG
    operations. This avoids globally tracing unrelated LangChain work.
    """

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        api_key: str | None = None,
        project_name: str | None = None,
    ):
        self.enabled = self._configured_enabled(enabled)
        self.api_key = (
            os.getenv("LANGSMITH_API_KEY")
            if api_key is None
            else api_key
        )
        self.project_name = (
            project_name
            or os.getenv("LANGSMITH_PROJECT")
            or "darwin-rag-v2"
        )

        if self.enabled and not (self.api_key or "").strip():
            raise LangSmithConfigurationError(
                "LANGSMITH_TRACING is enabled but LANGSMITH_API_KEY "
                "is missing. Add the key or disable tracing."
            )

    def start_session(
        self,
        *,
        allow_web_search: bool,
        vector_collection: str,
        thread_id: str,
        request_id: str,
        run_name: str,
        request_number: int,
    ) -> TraceSession:
        return TraceSession(
            run_id=uuid4(),
            enabled=self.enabled,
            project_name=self.project_name,
            tags=("darwin", "ragv2", "request"),
            metadata={
                "component": "ragv2",
                "thread_id": thread_id,
                "request_id": request_id,
                "request_number": request_number,
                "allow_web_search": allow_web_search,
                "vector_collection": vector_collection,
            },
            run_name=run_name,
        )

    def tracing_context(
        self,
        session: TraceSession,
    ) -> AbstractContextManager:
        if not session.enabled:
            return nullcontext()

        return ls.tracing_context(
            enabled=True,
            project_name=session.project_name,
            tags=list(session.tags),
            metadata=session.metadata,
        )

    @contextmanager
    def batch_context(
        self,
        *,
        batch_name: str,
        thread_id: str,
        questions: Sequence[str],
    ) -> Iterator[object | None]:
        """Makes several RAG requests children of one batch trace."""

        if not self.enabled:
            yield None
            return

        metadata = {
            "component": "ragv2",
            "thread_id": thread_id,
            "batch": True,
            "question_count": len(questions),
        }

        with ls.tracing_context(
            enabled=True,
            project_name=self.project_name,
            tags=["darwin", "ragv2", "batch"],
            metadata=metadata,
        ):
            with ls.trace(
                batch_name,
                run_type="chain",
                inputs={"question_count": len(questions)},
                project_name=self.project_name,
                tags=["darwin", "ragv2", "batch"],
                metadata=metadata,
            ) as run:
                yield run

    @staticmethod
    def _configured_enabled(enabled: bool | None) -> bool:
        if enabled is not None:
            return enabled

        if os.getenv("DARWIN_LANGSMITH_TRACING") is not None:
            return environment_flag("DARWIN_LANGSMITH_TRACING")

        return environment_flag("LANGSMITH_TRACING")

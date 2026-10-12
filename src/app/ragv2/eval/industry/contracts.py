"""Stable contracts shared by all external benchmark adapters.

These models are intentionally independent of RAGChecker, RAGAS, and BEIR.
They keep benchmark data portable and make framework upgrades an adapter
concern instead of a production-RAG concern.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class IndustryContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BenchmarkCase(IndustryContract):
    dataset: str = Field(min_length=1)
    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    reference_answer: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RetrievedContext(IndustryContract):
    doc_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    title: str | None = None
    source_uri: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    relevance_score: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
    )


class BenchmarkSample(IndustryContract):
    dataset: str = Field(min_length=1)
    query_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    reference_answer: str = Field(min_length=1)
    response: str = Field(min_length=1)
    retrieved_contexts: tuple[RetrievedContext, ...]
    grounded: bool
    abstained: bool
    latency_seconds: float = Field(ge=0.0)
    route_history: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)

    def as_ragchecker(self) -> dict[str, Any]:
        """Returns the exact record shape accepted by RAGChecker."""

        return {
            "query_id": self.query_id,
            "query": self.query,
            "gt_answer": self.reference_answer,
            "response": self.response,
            "retrieved_context": [
                {
                    "doc_id": context.doc_id,
                    "text": context.text,
                }
                for context in self.retrieved_contexts
            ],
        }

    def as_ragas(self) -> dict[str, Any]:
        """Returns a RAGAS SingleTurnSample-compatible dictionary."""

        return {
            "user_input": self.query,
            "retrieved_contexts": [
                context.text for context in self.retrieved_contexts
            ],
            "response": self.response,
            "reference": self.reference_answer,
        }

"""Industry-standard evaluation adapters for DARWIN RAG v2.

The package deliberately exchanges plain JSON-compatible records with
third-party evaluators. RAGChecker and RAGAS can therefore live in a separate
virtual environment without changing DARWIN's production dependencies.
"""

from app.ragv2.eval.industry.contracts import (
    BenchmarkCase,
    BenchmarkSample,
    RetrievedContext,
)

__all__ = (
    "BenchmarkCase",
    "BenchmarkSample",
    "RetrievedContext",
)

from collections.abc import Sequence
from hashlib import sha256
from typing import Protocol

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    Chunk,
    ContentType,
    ContextBundle,
    RetrievalHit,
    WebSearchResult,
)
from app.ragv2.ingest.chunking.tokenizer import (
    TiktokenCounter,
    TokenCounter,
)
from app.ragv2.retrieve.retrieval.context_builder import (
    ContextBuilder,
)
from app.ragv2.retrieve.retrieval.grader import EvidenceGrader


class WebSearchProvider(Protocol):
    def search(
        self,
        query: str,
        limit: int,
    ) -> Sequence[WebSearchResult]:
        ...


class DisabledWebSearchProvider:
    """Default provider: external search requires explicit wiring."""

    def search(
        self,
        query: str,
        limit: int,
    ) -> Sequence[WebSearchResult]:
        return ()


class WebEvidenceRetriever:
    """Grades approved web results and converts them to RAG context."""

    def __init__(
        self,
        provider: WebSearchProvider | None = None,
        evidence_grader: EvidenceGrader | None = None,
        context_builder: ContextBuilder | None = None,
        token_counter: TokenCounter | None = None,
        rag_settings: RagSettings = settings,
    ):
        self.provider = provider or DisabledWebSearchProvider()
        self.evidence_grader = (
            evidence_grader
            or EvidenceGrader(rag_settings=rag_settings)
        )
        self.context_builder = (
            context_builder
            or ContextBuilder(rag_settings=rag_settings)
        )
        self.token_counter = token_counter or TiktokenCounter()
        self.settings = rag_settings

    def retrieve(self, query: str) -> ContextBundle:
        query = query.strip()

        if not query:
            raise ValueError("Web retrieval query cannot be empty.")

        try:
            results = tuple(
                self.provider.search(
                    query,
                    self.settings.web_search_result_limit,
                )
            )
        except Exception:
            results = ()

        if not results:
            return self._empty_context(query)

        hits = tuple(
            self._to_hit(result, rank)
            for rank, result in enumerate(results, start=1)
        )
        grades = self.evidence_grader.grade(query, hits)
        return self.context_builder.build(query, grades)

    def _to_hit(
        self,
        result: WebSearchResult,
        rank: int,
    ) -> RetrievalHit:
        identity = sha256(
            f"{result.url}\n{result.text}".encode("utf-8")
        ).hexdigest()[:24]
        token_count = max(
            1,
            self.token_counter.count(result.text),
        )

        return RetrievalHit(
            chunk=Chunk(
                chunk_id=f"web-{identity}",
                document_id=f"web-document-{identity}",
                parent_id=f"web-parent-{identity}",
                text=result.text,
                content_type=ContentType.TEXT,
                source_uri=result.url,
                token_count=token_count,
                metadata={
                    "document_title": result.title,
                    "external_web_evidence": True,
                },
            ),
            score=result.score,
            rank=rank,
            retriever="web",
            raw_score=result.score,
        )

    @staticmethod
    def _empty_context(query: str) -> ContextBundle:
        return ContextBundle(
            query=query,
            items=(),
            total_tokens=0,
            has_direct_evidence=False,
        )

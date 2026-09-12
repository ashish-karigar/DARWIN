from collections.abc import Sequence
from math import exp
from typing import Any, Protocol

import numpy as np
from sentence_transformers import CrossEncoder

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import RetrievalHit


class PassageScorer(Protocol):
    def score(
        self,
        pairs: Sequence[tuple[str, str]],
    ) -> list[float]:
        ...


class CrossEncoderScorer:
    """Lazily loads and runs a local cross-encoder model."""

    def __init__(
        self,
        model_name: str = settings.reranker_model,
        batch_size: int = settings.reranker_batch_size,
        model: Any | None = None,
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = model

    def score(
        self,
        pairs: Sequence[tuple[str, str]],
    ) -> list[float]:
        if not pairs:
            return []

        predictions = self._get_model().predict(
            list(pairs),
            batch_size=self.batch_size,
            show_progress_bar=False,
        )

        return (
            np.asarray(predictions, dtype=float)
            .reshape(-1)
            .tolist()
        )

    def _get_model(self) -> CrossEncoder:
        if self._model is None:
            self._model = CrossEncoder(self.model_name)

        return self._model


class CrossEncoderReranker:
    """Reorders retrieved candidates by question-passage relevance."""

    def __init__(
        self,
        scorer: PassageScorer | None = None,
        rag_settings: RagSettings = settings,
    ):
        self.settings = rag_settings
        self.scorer = scorer or CrossEncoderScorer(
            model_name=rag_settings.reranker_model,
            batch_size=rag_settings.reranker_batch_size,
        )

    def rerank(
        self,
        query: str,
        hits: Sequence[RetrievalHit],
        limit: int | None = None,
    ) -> tuple[RetrievalHit, ...]:
        if not query.strip():
            raise ValueError("Reranking query cannot be empty.")

        final_limit = (
            limit
            if limit is not None
            else self.settings.reranker_result_limit
        )

        if final_limit < 1:
            raise ValueError(
                "Reranking limit must be positive."
            )

        hits = tuple(hits)

        if not hits:
            return ()

        pairs = [
            (
                query,
                self._passage_text(hit),
            )
            for hit in hits
        ]

        raw_scores = self.scorer.score(pairs)

        if len(raw_scores) != len(hits):
            raise RuntimeError(
                "Reranker returned an unexpected score count."
            )

        scored_hits = sorted(
            zip(hits, raw_scores),
            key=lambda item: (
                -item[1],
                item[0].chunk.chunk_id,
            ),
        )[:final_limit]

        return tuple(
            RetrievalHit(
                chunk=hit.chunk,
                score=self._sigmoid(raw_score),
                raw_score=raw_score,
                rank=rank,
                retriever="reranker",
                metadata={
                    **hit.metadata,
                    "previous_rank": hit.rank,
                    "previous_score": hit.score,
                    "previous_retriever": hit.retriever,
                },
            )
            for rank, (hit, raw_score) in enumerate(
                scored_hits,
                start=1,
            )
        )

    @staticmethod
    def _passage_text(hit: RetrievalHit) -> str:
        heading = " > ".join(hit.chunk.heading_path)

        if not heading:
            return hit.chunk.text

        return f"Heading: {heading}\n{hit.chunk.text}"

    @staticmethod
    def _sigmoid(value: float) -> float:
        if value >= 0:
            return 1.0 / (1.0 + exp(-value))

        exponential = exp(value)
        return exponential / (1.0 + exponential)
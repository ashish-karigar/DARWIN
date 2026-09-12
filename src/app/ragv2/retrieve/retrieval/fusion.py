from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from app.ragv2.contracts import Chunk, RetrievalHit


@dataclass(slots=True)
class _FusionCandidate:
    chunk: Chunk
    fusion_score: float = 0.0
    component_ranks: dict[str, int] = field(
        default_factory=dict
    )
    component_scores: dict[str, float] = field(
        default_factory=dict
    )


class ReciprocalRankFusion:
    """Combines ranked results without comparing incompatible raw scores."""

    def __init__(
        self,
        rank_constant: int = 60,
        retriever_weights: Mapping[str, float] | None = None,
    ):
        if rank_constant < 1:
            raise ValueError(
                "Fusion rank constant must be positive."
            )

        self.rank_constant = rank_constant
        self.retriever_weights = dict(
            retriever_weights or {}
        )

        if any(
            weight < 0
            for weight in self.retriever_weights.values()
        ):
            raise ValueError(
                "Retriever weights cannot be negative."
            )

    def fuse(
        self,
        ranked_results: Mapping[
            str,
            Sequence[RetrievalHit],
        ],
        limit: int = 10,
    ) -> tuple[RetrievalHit, ...]:
        if limit < 1:
            raise ValueError("Fusion limit must be positive.")

        candidates: dict[str, _FusionCandidate] = {}

        for retriever_name, hits in ranked_results.items():
            weight = self.retriever_weights.get(
                retriever_name,
                1.0,
            )
            seen_chunk_ids = set()

            for hit in hits:
                chunk_id = hit.chunk.chunk_id

                if chunk_id in seen_chunk_ids:
                    continue

                seen_chunk_ids.add(chunk_id)

                candidate = candidates.setdefault(
                    chunk_id,
                    _FusionCandidate(chunk=hit.chunk),
                )

                candidate.fusion_score += (
                    weight
                    / (self.rank_constant + hit.rank)
                )
                candidate.component_ranks[
                    retriever_name
                ] = hit.rank
                candidate.component_scores[
                    retriever_name
                ] = hit.score

        ordered = sorted(
            candidates.values(),
            key=lambda candidate: (
                -candidate.fusion_score,
                candidate.chunk.chunk_id,
            ),
        )[:limit]

        if not ordered:
            return ()

        strongest_score = ordered[0].fusion_score

        return tuple(
            RetrievalHit(
                chunk=candidate.chunk,
                score=(
                    candidate.fusion_score
                    / strongest_score
                    if strongest_score > 0
                    else 0.0
                ),
                raw_score=candidate.fusion_score,
                rank=rank,
                retriever="hybrid",
                metadata={
                    "matched_retrievers": tuple(
                        candidate.component_ranks
                    ),
                    "component_ranks": (
                        candidate.component_ranks
                    ),
                    "component_scores": (
                        candidate.component_scores
                    ),
                },
            )
            for rank, candidate in enumerate(
                ordered,
                start=1,
            )
        )
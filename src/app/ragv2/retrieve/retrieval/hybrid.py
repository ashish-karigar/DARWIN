from concurrent.futures import ThreadPoolExecutor

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    ContentType,
    RetrievalHit,
)
from app.ragv2.ingest.indexes.lexical import (
    LexicalIndex,
    SQLiteLexicalIndex,
)
from app.ragv2.ingest.indexes.vector import (
    ChromaVectorIndex,
    VectorIndex,
)
from app.ragv2.retrieve.retrieval.fusion import (
    ReciprocalRankFusion,
)


class HybridRetriever:
    """Runs semantic and lexical retrieval, then fuses the rankings."""

    def __init__(
        self,
        vector_index: VectorIndex | None = None,
        lexical_index: LexicalIndex | None = None,
        fusion: ReciprocalRankFusion | None = None,
        rag_settings: RagSettings = settings,
    ):
        self.settings = rag_settings
        self.vector_index = (
            vector_index or ChromaVectorIndex(rag_settings)
        )
        self.lexical_index = (
            lexical_index
            or SQLiteLexicalIndex(
                rag_settings.lexical_index_path
            )
        )
        self.fusion = (
            fusion
            or ReciprocalRankFusion(
                rank_constant=rag_settings.rrf_rank_constant,
                retriever_weights={
                    "vector": (
                        rag_settings.vector_retriever_weight
                    ),
                    "lexical": (
                        rag_settings.lexical_retriever_weight
                    ),
                },
            )
        )

    def search(
        self,
        query: str,
        limit: int | None = None,
        document_id: str | None = None,
        content_type: ContentType | None = None,
    ) -> tuple[RetrievalHit, ...]:
        if not query.strip():
            raise ValueError(
                "Hybrid search query cannot be empty."
            )

        final_limit = (
            limit
            if limit is not None
            else self.settings.retrieval_result_limit
        )

        if final_limit < 1:
            raise ValueError(
                "Hybrid search limit must be positive."
            )

        candidate_limit = max(
            final_limit,
            self.settings.retrieval_candidate_limit,
        )

        vector_filter = self._build_vector_filter(
            document_id=document_id,
            content_type=content_type,
        )

        with ThreadPoolExecutor(max_workers=2) as executor:
            vector_future = executor.submit(
                self.vector_index.search,
                query=query,
                limit=candidate_limit,
                where=vector_filter,
            )

            lexical_future = executor.submit(
                self.lexical_index.search,
                query=query,
                limit=candidate_limit,
                document_id=document_id,
                content_type=content_type,
            )

            vector_hits = vector_future.result()
            lexical_hits = lexical_future.result()

        return self.fusion.fuse(
            {
                "vector": vector_hits,
                "lexical": lexical_hits,
            },
            limit=final_limit,
        )

    @staticmethod
    def _build_vector_filter(
        document_id: str | None,
        content_type: ContentType | None,
    ) -> dict | None:
        filters = []

        if document_id is not None:
            filters.append(
                {"document_id": document_id}
            )

        if content_type is not None:
            filters.append(
                {"content_type": content_type.value}
            )

        if not filters:
            return None

        if len(filters) == 1:
            return filters[0]

        return {"$and": filters}
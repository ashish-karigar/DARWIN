import re
import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from app.ragv2.config import settings
from app.ragv2.contracts import (
    Chunk,
    ContentType,
    RetrievalHit,
)
from app.ragv2.ingest.indexes.search_text import (
    build_search_text,
)


class LexicalIndex(Protocol):
    def upsert(self, chunks: Sequence[Chunk]) -> None:
        ...

    def search(
        self,
        query: str,
        limit: int = 5,
    ) -> tuple[RetrievalHit, ...]:
        ...

    def delete_document(self, document_id: str) -> int:
        ...


class SQLiteLexicalIndex:
    """Provides persistent keyword retrieval using FTS5 and BM25."""

    def __init__(
        self,
        database_path: str | Path = settings.lexical_index_path,
    ):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._initialize()

    def upsert(self, chunks: Sequence[Chunk]) -> None:
        chunks = tuple(chunks)

        if not chunks:
            return

        chunk_ids = [chunk.chunk_id for chunk in chunks]

        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError(
                "Lexical upsert received duplicate chunk IDs."
            )

        with self._connect() as connection:
            connection.executemany(
                """
                DELETE FROM lexical_chunks
                WHERE chunk_id = ?
                """,
                [(chunk_id,) for chunk_id in chunk_ids],
            )

            connection.executemany(
                """
                INSERT INTO lexical_chunks (
                    chunk_id,
                    document_id,
                    content_type,
                    text,
                    chunk_json
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.document_id,
                        chunk.content_type.value,
                        build_search_text(chunk),
                        chunk.model_dump_json(),
                    )
                    for chunk in chunks
                ],
            )

    def search(
            self,
            query: str,
            limit: int = 5,
            document_id: str | None = None,
            content_type: ContentType | None = None,
    ) -> tuple[RetrievalHit, ...]:
        ...
        if not query.strip():
            raise ValueError("Lexical search query cannot be empty.")

        if limit < 1:
            raise ValueError("Lexical search limit must be positive.")

        match_query = self._safe_match_query(query)

        if not match_query:
            return ()

        conditions = ["lexical_chunks MATCH ?"]
        parameters = [match_query]

        if document_id is not None:
            conditions.append("document_id = ?")
            parameters.append(document_id)

        if content_type is not None:
            conditions.append("content_type = ?")
            parameters.append(content_type.value)

        parameters.append(limit)

        sql = f"""
            SELECT
                chunk_json,
                bm25(lexical_chunks) AS bm25_score
            FROM lexical_chunks
            WHERE {" AND ".join(conditions)}
            ORDER BY bm25_score
            LIMIT ?
        """

        with self._connect() as connection:
            rows = connection.execute(
                sql,
                parameters,
            ).fetchall()

        if not rows:
            return ()

        relevances = [
            max(0.0, -float(row["bm25_score"]))
            for row in rows
        ]
        strongest_relevance = max(relevances)

        hits = []

        for rank, (row, relevance) in enumerate(
            zip(rows, relevances),
            start=1,
        ):
            score = (
                relevance / strongest_relevance
                if strongest_relevance > 0
                else 0.0
            )

            hits.append(
                RetrievalHit(
                    chunk=Chunk.model_validate_json(
                        row["chunk_json"]
                    ),
                    score=score,
                    raw_score=float(row["bm25_score"]),
                    rank=rank,
                    retriever="lexical",
                )
            )

        return tuple(hits)

    def delete_document(self, document_id: str) -> int:
        with self._connect() as connection:
            count = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM lexical_chunks
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()["total"]

            connection.execute(
                """
                DELETE FROM lexical_chunks
                WHERE document_id = ?
                """,
                (document_id,),
            )

        return int(count)

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total
                FROM lexical_chunks
                """
            ).fetchone()

        return int(row["total"])

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS lexical_chunks
                USING fts5(
                    chunk_id UNINDEXED,
                    document_id UNINDEXED,
                    content_type UNINDEXED,
                    text,
                    chunk_json UNINDEXED,
                    tokenize='porter unicode61'
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row

        return connection

    @staticmethod
    def _safe_match_query(query: str) -> str:
        terms = list(
            dict.fromkeys(
                re.findall(
                    r"\w+",
                    query.casefold(),
                    flags=re.UNICODE,
                )
            )
        )

        return " OR ".join(
            f'"{term}"'
            for term in terms
        )
import sqlite3
from pathlib import Path
from typing import Protocol, TypeAlias

from app.ragv2.config import settings
from app.ragv2.contracts import (
    DocumentImage,
    DocumentSection,
    DocumentTable,
    ParsedDocument,
)


ParentContent: TypeAlias = (
    DocumentSection
    | DocumentTable
    | DocumentImage
)


class DocumentStore(Protocol):
    def store(self, document: ParsedDocument) -> None:
        ...

    def get_document(
        self,
        document_id: str,
    ) -> ParsedDocument | None:
        ...

    def get_parent(
        self,
        parent_id: str,
    ) -> ParentContent | None:
        ...

    def delete(self, document_id: str) -> bool:
        ...


class SQLiteDocumentStore:
    """Persists normalized documents and directly addressable parents."""

    def __init__(
        self,
        database_path: str | Path = settings.document_store_path,
    ):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        self._initialize()

    def store(self, document: ParsedDocument) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO documents (
                    document_id,
                    payload_json
                )
                VALUES (?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    payload_json = excluded.payload_json
                """,
                (
                    document.document_id,
                    document.model_dump_json(),
                ),
            )

            connection.execute(
                """
                DELETE FROM parents
                WHERE document_id = ?
                """,
                (document.document_id,),
            )

            connection.executemany(
                """
                INSERT INTO parents (
                    parent_id,
                    document_id,
                    parent_type,
                    payload_json
                )
                VALUES (?, ?, ?, ?)
                """,
                self._parent_rows(document),
            )

    def get_document(
        self,
        document_id: str,
    ) -> ParsedDocument | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT payload_json
                FROM documents
                WHERE document_id = ?
                """,
                (document_id,),
            ).fetchone()

        if row is None:
            return None

        return ParsedDocument.model_validate_json(
            row["payload_json"]
        )

    def get_parent(
        self,
        parent_id: str,
    ) -> ParentContent | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT parent_type, payload_json
                FROM parents
                WHERE parent_id = ?
                """,
                (parent_id,),
            ).fetchone()

        if row is None:
            return None

        parent_models = {
            "section": DocumentSection,
            "table": DocumentTable,
            "image": DocumentImage,
        }

        model = parent_models[row["parent_type"]]

        return model.model_validate_json(row["payload_json"])

    def delete(self, document_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                DELETE FROM documents
                WHERE document_id = ?
                """,
                (document_id,),
            )

        return cursor.rowcount > 0

    def count_documents(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM documents"
            ).fetchone()

        return int(row["total"])

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS parents (
                    parent_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    parent_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    FOREIGN KEY(document_id)
                        REFERENCES documents(document_id)
                        ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS
                    idx_parents_document_id
                ON parents(document_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")

        return connection

    @staticmethod
    def _parent_rows(
        document: ParsedDocument,
    ) -> list[tuple[str, str, str, str]]:
        rows = []

        for section in document.sections:
            rows.append(
                (
                    section.section_id,
                    document.document_id,
                    "section",
                    section.model_dump_json(),
                )
            )

        for table in document.tables:
            rows.append(
                (
                    table.table_id,
                    document.document_id,
                    "table",
                    table.model_dump_json(),
                )
            )

        for image in document.images:
            rows.append(
                (
                    image.image_id,
                    document.document_id,
                    "image",
                    image.model_dump_json(),
                )
            )

        return rows
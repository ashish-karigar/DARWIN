import json
import re
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Protocol

from app.ragv2.config import settings
from app.ragv2.contracts import DocumentTable, ParsedDocument


@dataclass(frozen=True, slots=True)
class StructuredRow:
    document_id: str
    table_id: str
    row_index: int
    values: dict[str, str]
    caption: str | None
    page_number: int | None


@dataclass(frozen=True, slots=True)
class AggregateResult:
    operation: str
    column: str | None
    value: float | int | None
    matched_rows: int


@dataclass(frozen=True, slots=True)
class StructuredTableSchema:
    document_id: str
    table_id: str
    columns: tuple[str, ...]
    caption: str | None
    page_number: int | None


class StructuredIndex(Protocol):
    def upsert(self, document: ParsedDocument) -> int:
        ...

    def delete_document(self, document_id: str) -> int:
        ...

    def schemas(self) -> tuple[StructuredTableSchema, ...]:
        ...


class SQLiteStructuredIndex:
    """Stores table rows for exact filtering and aggregation."""

    def __init__(
        self,
        database_path: str | Path = settings.structured_index_path,
    ):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def upsert(self, document: ParsedDocument) -> int:
        rows = [
            row
            for table in document.tables
            for row in self._table_rows(document, table)
        ]

        with self._connect() as connection:
            connection.execute(
                "DELETE FROM structured_rows WHERE document_id = ?",
                (document.document_id,),
            )
            connection.executemany(
                """
                INSERT INTO structured_rows (
                    document_id,
                    table_id,
                    row_index,
                    values_json,
                    searchable_text,
                    caption,
                    page_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        row.document_id,
                        row.table_id,
                        row.row_index,
                        json.dumps(row.values, sort_keys=True),
                        " ".join(row.values.values()).casefold(),
                        row.caption,
                        row.page_number,
                    )
                    for row in rows
                ),
            )

        return len(rows)

    def delete_document(self, document_id: str) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM structured_rows WHERE document_id = ?",
                (document_id,),
            )
        return cursor.rowcount

    def search(
        self,
        query: str,
        *,
        document_id: str | None = None,
        table_id: str | None = None,
        limit: int = 20,
    ) -> tuple[StructuredRow, ...]:
        query = query.strip().casefold()

        if not query:
            raise ValueError("Structured search query cannot be empty.")

        clauses = ["searchable_text LIKE ?"]
        parameters: list[object] = [f"%{query}%"]

        if document_id:
            clauses.append("document_id = ?")
            parameters.append(document_id)

        if table_id:
            clauses.append("table_id = ?")
            parameters.append(table_id)

        parameters.append(max(1, limit))

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM structured_rows
                WHERE {' AND '.join(clauses)}
                ORDER BY document_id, table_id, row_index
                LIMIT ?
                """,
                parameters,
            ).fetchall()

        return tuple(self._from_database(row) for row in rows)

    def filter_rows(
        self,
        filters: Mapping[str, str],
        *,
        document_id: str | None = None,
        table_id: str | None = None,
    ) -> tuple[StructuredRow, ...]:
        rows = self._load_rows(
            document_id=document_id,
            table_id=table_id,
        )

        normalized_filters = {
            key.casefold(): value.strip().casefold()
            for key, value in filters.items()
        }

        return tuple(
            row
            for row in rows
            if all(
                self._value_for_column(row.values, column)
                .strip()
                .casefold()
                == expected
                for column, expected in normalized_filters.items()
            )
        )

    def aggregate(
        self,
        operation: str,
        *,
        column: str | None = None,
        filters: Mapping[str, str] | None = None,
        document_id: str | None = None,
        table_id: str | None = None,
    ) -> AggregateResult:
        operation = operation.strip().casefold()
        rows = (
            self.filter_rows(
                filters,
                document_id=document_id,
                table_id=table_id,
            )
            if filters
            else self._load_rows(
                document_id=document_id,
                table_id=table_id,
            )
        )

        if operation == "count":
            return AggregateResult(
                operation=operation,
                column=column,
                value=len(rows),
                matched_rows=len(rows),
            )

        if not column:
            raise ValueError(
                f"Column is required for {operation} aggregation."
            )

        values = tuple(
            value
            for row in rows
            if (
                value := self._numeric_value(
                    self._value_for_column(row.values, column)
                )
            )
            is not None
        )

        if operation == "sum":
            result = sum(values, Decimal(0))
        elif operation == "average":
            result = (
                sum(values, Decimal(0)) / len(values)
                if values
                else None
            )
        elif operation == "minimum":
            result = min(values) if values else None
        elif operation == "maximum":
            result = max(values) if values else None
        else:
            raise ValueError(
                "Unsupported aggregation. Use count, sum, average, "
                "minimum, or maximum."
            )

        return AggregateResult(
            operation=operation,
            column=column,
            value=float(result) if result is not None else None,
            matched_rows=len(values),
        )

    def count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS total FROM structured_rows"
            ).fetchone()
        return int(row["total"])

    def schemas(self) -> tuple[StructuredTableSchema, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT document_id, table_id, values_json,
                       caption, page_number
                FROM structured_rows
                GROUP BY document_id, table_id
                ORDER BY document_id, table_id
                """
            ).fetchall()

        return tuple(
            StructuredTableSchema(
                document_id=row["document_id"],
                table_id=row["table_id"],
                columns=tuple(
                    json.loads(row["values_json"]).keys()
                ),
                caption=row["caption"],
                page_number=row["page_number"],
            )
            for row in rows
        )

    def _load_rows(
        self,
        *,
        document_id: str | None,
        table_id: str | None,
    ) -> tuple[StructuredRow, ...]:
        clauses = []
        parameters = []

        if document_id:
            clauses.append("document_id = ?")
            parameters.append(document_id)

        if table_id:
            clauses.append("table_id = ?")
            parameters.append(table_id)

        where = (
            f"WHERE {' AND '.join(clauses)}"
            if clauses
            else ""
        )

        with self._connect() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM structured_rows
                {where}
                ORDER BY document_id, table_id, row_index
                """,
                parameters,
            ).fetchall()

        return tuple(self._from_database(row) for row in rows)

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS structured_rows (
                    document_id TEXT NOT NULL,
                    table_id TEXT NOT NULL,
                    row_index INTEGER NOT NULL,
                    values_json TEXT NOT NULL,
                    searchable_text TEXT NOT NULL,
                    caption TEXT,
                    page_number INTEGER,
                    PRIMARY KEY (document_id, table_id, row_index)
                );

                CREATE INDEX IF NOT EXISTS idx_structured_document
                ON structured_rows(document_id);

                CREATE INDEX IF NOT EXISTS idx_structured_table
                ON structured_rows(table_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    @classmethod
    def _table_rows(
        cls,
        document: ParsedDocument,
        table: DocumentTable,
    ) -> tuple[StructuredRow, ...]:
        parsed_rows = cls._parse_markdown(table.markdown)
        return tuple(
            StructuredRow(
                document_id=document.document_id,
                table_id=table.table_id,
                row_index=index,
                values=values,
                caption=table.caption,
                page_number=table.page_number,
            )
            for index, values in enumerate(parsed_rows)
        )

    @classmethod
    def _parse_markdown(
        cls,
        markdown: str,
    ) -> tuple[dict[str, str], ...]:
        lines = [
            line.strip()
            for line in markdown.splitlines()
            if "|" in line
        ]

        separator_index = next(
            (
                index
                for index, line in enumerate(lines)
                if cls._is_separator(line)
            ),
            None,
        )

        if separator_index is None or separator_index == 0:
            return ()

        headers = cls._unique_headers(
            cls._split_row(lines[separator_index - 1])
        )
        result = []

        for line in lines[separator_index + 1:]:
            cells = cls._split_row(line)

            if not cells:
                continue

            cells.extend([""] * (len(headers) - len(cells)))
            result.append(dict(zip(headers, cells, strict=False)))

        return tuple(result)

    @staticmethod
    def _split_row(line: str) -> list[str]:
        placeholder = "\u0000PIPE\u0000"
        protected = line.replace(r"\|", placeholder)
        return [
            cell.strip().replace(placeholder, "|")
            for cell in protected.strip().strip("|").split("|")
        ]

    @classmethod
    def _is_separator(cls, line: str) -> bool:
        cells = cls._split_row(line)
        return bool(cells) and all(
            re.fullmatch(r":?-{3,}:?", cell)
            for cell in cells
        )

    @staticmethod
    def _unique_headers(headers: Sequence[str]) -> list[str]:
        result = []
        counts = {}

        for index, raw_header in enumerate(headers, start=1):
            base = raw_header.strip() or f"column_{index}"
            count = counts.get(base.casefold(), 0) + 1
            counts[base.casefold()] = count
            result.append(base if count == 1 else f"{base}_{count}")

        return result

    @staticmethod
    def _value_for_column(
        values: Mapping[str, str],
        requested_column: str,
    ) -> str:
        requested = requested_column.casefold()

        for column, value in values.items():
            if column.casefold() == requested:
                return value

        return ""

    @staticmethod
    def _numeric_value(value: str) -> Decimal | None:
        if re.search(r"[A-Za-z]", value):
            return None

        cleaned = value.strip().replace(",", "")
        negative = cleaned.startswith("(") and cleaned.endswith(")")
        cleaned = re.sub(r"[^0-9.+-]", "", cleaned)

        if not cleaned:
            return None

        try:
            number = Decimal(cleaned)
        except InvalidOperation:
            return None

        return -number if negative else number

    @staticmethod
    def _from_database(row: sqlite3.Row) -> StructuredRow:
        return StructuredRow(
            document_id=row["document_id"],
            table_id=row["table_id"],
            row_index=row["row_index"],
            values=json.loads(row["values_json"]),
            caption=row["caption"],
            page_number=row["page_number"],
        )

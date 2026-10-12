import re
from collections.abc import Mapping
from dataclasses import dataclass

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    ContentType,
    ContextBundle,
    ContextItem,
)
from app.ragv2.ingest.chunking.tokenizer import (
    TiktokenCounter,
    TokenCounter,
)
from app.ragv2.ingest.indexes.document_store import (
    DocumentStore,
    SQLiteDocumentStore,
)
from app.ragv2.ingest.indexes.structured import (
    SQLiteStructuredIndex,
    StructuredTableSchema,
)


@dataclass(frozen=True, slots=True)
class _StructuredPlan:
    schema: StructuredTableSchema
    column: str | None
    filters: dict[str, str]
    score: int


class StructuredQueryEngine:
    """Executes explicit table aggregations without model arithmetic."""

    OPERATIONS = (
        (re.compile(r"\b(total|sum)\b", re.IGNORECASE), "sum"),
        (re.compile(r"\b(average|mean)\b", re.IGNORECASE), "average"),
        (re.compile(r"\b(minimum|lowest)\b", re.IGNORECASE), "minimum"),
        (re.compile(r"\b(maximum|highest)\b", re.IGNORECASE), "maximum"),
        (
            re.compile(
                r"\b(count|number of)\s+(rows|records|entries|items)\b",
                re.IGNORECASE,
            ),
            "count",
        ),
    )

    def __init__(
        self,
        structured_index: SQLiteStructuredIndex | None = None,
        document_store: DocumentStore | None = None,
        token_counter: TokenCounter | None = None,
        rag_settings: RagSettings = settings,
    ):
        self.structured_index = (
            structured_index or SQLiteStructuredIndex()
        )
        self.document_store = (
            document_store or SQLiteDocumentStore()
        )
        self.token_counter = token_counter or TiktokenCounter()
        self.settings = rag_settings

    def retrieve(self, query: str) -> ContextBundle:
        query = query.strip()

        if not query:
            raise ValueError("Structured query cannot be empty.")

        operation = self._operation(query)

        if operation is None:
            return self._empty(query)

        plan = self._plan(query, operation)

        if plan is None:
            return self._empty(query)

        schema = plan.schema
        column = plan.column
        filters = plan.filters
        aggregate = self.structured_index.aggregate(
            operation,
            column=column,
            filters=filters,
            document_id=schema.document_id,
            table_id=schema.table_id,
        )
        rows = self.structured_index.filter_rows(
            filters,
            document_id=schema.document_id,
            table_id=schema.table_id,
        )[
            :self.settings.structured_evidence_row_limit
        ]

        if aggregate.value is None or aggregate.matched_rows == 0:
            return self._empty(query)

        document = self.document_store.get_document(
            schema.document_id
        )
        source_uri = (
            document.source_uri if document else schema.document_id
        )
        title = document.title if document else schema.document_id
        evidence = self._format_evidence(
            operation,
            column,
            filters,
            aggregate.value,
            aggregate.matched_rows,
            rows,
        )

        return ContextBundle(
            query=query,
            items=(
                ContextItem(
                    parent_id=schema.table_id,
                    document_id=schema.document_id,
                    document_title=title,
                    text=evidence,
                    content_type=ContentType.TABLE,
                    source_uri=source_uri,
                    page_number=schema.page_number,
                    heading_path=(
                        (schema.caption,)
                        if schema.caption
                        else ()
                    ),
                    supporting_chunk_ids=(
                        f"structured:{schema.table_id}",
                    ),
                    relevance_score=1.0,
                    directly_answers=True,
                    expanded_from_parent=False,
                ),
            ),
            total_tokens=self.token_counter.count(evidence),
            has_direct_evidence=True,
        )

    def _plan(
        self,
        query: str,
        operation: str,
    ) -> _StructuredPlan | None:
        normalized_query = self._normalize(query)
        query_terms = set(normalized_query.split())
        candidates = []

        for schema in self.structured_index.schemas():
            rows = self.structured_index.filter_rows(
                {},
                document_id=schema.document_id,
                table_id=schema.table_id,
            )
            mentioned_columns = tuple(
                value
                for value in schema.columns
                if self._normalize(value) in normalized_query
            )
            numeric_columns = tuple(
                column
                for column in mentioned_columns
                if self._is_numeric_column(rows, column)
            )
            column = (
                numeric_columns[0]
                if numeric_columns
                else (
                    mentioned_columns[0]
                    if operation == "count" and mentioned_columns
                    else None
                )
            )

            if operation != "count" and column is None:
                continue

            filters = self._infer_filters(
                normalized_query,
                rows,
                excluded_column=column,
            )

            if filters is None:
                continue

            if (
                not filters
                and self._has_filter_qualifier(normalized_query)
            ):
                # A qualifier that does not match any stored value is
                # safer to reject than to accidentally aggregate all rows.
                continue

            document = self.document_store.get_document(
                schema.document_id
            )
            descriptor = " ".join(
                value
                for value in (
                    schema.caption or "",
                    document.title if document else "",
                    document.source_uri if document else "",
                )
                if value
            )
            descriptor_terms = set(
                self._normalize(descriptor).split()
            )
            descriptor_matches = len(
                query_terms & descriptor_terms
            )

            if operation == "count" and not (
                column
                or filters
                or (
                    schema.caption
                    and self._normalize(schema.caption)
                    in normalized_query
                )
            ):
                continue

            candidates.append(
                _StructuredPlan(
                    schema=schema,
                    column=column,
                    filters=filters,
                    score=(
                        (5 if column else 0)
                        + (4 * len(filters))
                        + min(3, descriptor_matches)
                    ),
                )
            )

        if not candidates:
            return None

        candidates.sort(
            key=lambda candidate: (
                -candidate.score,
                candidate.schema.document_id,
                candidate.schema.table_id,
            )
        )
        best = candidates[0]

        if (
            len(candidates) > 1
            and candidates[1].score == best.score
        ):
            return None

        return best

    @classmethod
    def supports(cls, query: str) -> bool:
        """Returns whether the query requests deterministic arithmetic."""

        return cls._operation(query.strip()) is not None

    @classmethod
    def _infer_filters(
        cls,
        normalized_query: str,
        rows,
        *,
        excluded_column: str | None,
    ) -> dict[str, str] | None:
        candidates = {}

        for row in rows:
            for column, value in row.values.items():
                normalized_value = cls._normalize(value)

                if (
                    column == excluded_column
                    or len(normalized_value) < 2
                    or cls._looks_numeric(value)
                    or normalized_value not in normalized_query
                ):
                    continue

                existing = candidates.get(column)

                if (
                    existing is not None
                    and existing.casefold() != value.casefold()
                ):
                    return None

                candidates.setdefault(column, value)

        return candidates

    @staticmethod
    def _has_filter_qualifier(normalized_query: str) -> bool:
        return bool(
            re.search(
                r"\b(for|where|during|within)\b",
                normalized_query,
            )
        )

    @classmethod
    def _is_numeric_column(
        cls,
        rows,
        column: str,
    ) -> bool:
        values = [
            row.values.get(column, "")
            for row in rows
            if row.values.get(column, "").strip()
        ]

        if not values:
            return False

        numeric = sum(
            cls._looks_numeric(value)
            for value in values
        )
        return numeric / len(values) >= 0.8

    @staticmethod
    def _format_evidence(
        operation: str,
        column: str | None,
        filters: Mapping[str, str],
        value: float | int,
        matched_rows: int,
        rows,
    ) -> str:
        filter_text = (
            ", ".join(
                f"{key} = {item}"
                for key, item in filters.items()
            )
            or "none"
        )
        row_text = "\n".join(
            " | ".join(
                f"{key}: {item}"
                for key, item in row.values.items()
            )
            for row in rows
        )

        return (
            f"Deterministic table calculation\n"
            f"Operation: {operation}\n"
            f"Column: {column or 'rows'}\n"
            f"Filters: {filter_text}\n"
            f"Matched rows: {matched_rows}\n"
            f"Result: {value}\n"
            f"Input rows:\n{row_text}"
        )

    @classmethod
    def _operation(cls, query: str) -> str | None:
        return next(
            (
                operation
                for pattern, operation in cls.OPERATIONS
                if pattern.search(query)
            ),
            None,
        )

    @staticmethod
    def _normalize(value: str) -> str:
        return " ".join(
            re.sub(r"[^a-z0-9]+", " ", value.casefold()).split()
        )

    @staticmethod
    def _looks_numeric(value: str) -> bool:
        return bool(
            re.fullmatch(
                r"[\s$€£¥()%,.+\-0-9]+",
                value,
            )
        )

    @staticmethod
    def _empty(query: str) -> ContextBundle:
        return ContextBundle(
            query=query,
            items=(),
            total_tokens=0,
            has_direct_evidence=False,
        )

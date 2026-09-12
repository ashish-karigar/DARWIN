from collections.abc import Sequence
from dataclasses import dataclass, field

from app.ragv2.config import RagSettings, settings
from app.ragv2.contracts import (
    ContextBundle,
    ContextItem,
    DocumentImage,
    DocumentSection,
    DocumentTable,
    EvidenceGrade,
)
from app.ragv2.ingest.chunking.tokenizer import (
    TiktokenCounter,
    TokenCounter,
)
from app.ragv2.ingest.indexes.document_store import (
    DocumentStore,
    ParentContent,
    SQLiteDocumentStore,
)


@dataclass(slots=True)
class _ParentCandidate:
    grades: list[EvidenceGrade] = field(
        default_factory=list
    )

    @property
    def directly_answers(self) -> bool:
        return any(
            grade.directly_answers
            for grade in self.grades
        )

    @property
    def relevance_score(self) -> float:
        return max(
            grade.relevance_score
            for grade in self.grades
        )

    @property
    def best_rank(self) -> int:
        return min(
            grade.hit.rank
            for grade in self.grades
        )


class ContextBuilder:
    """Expands graded child hits into token-bounded parent context."""

    def __init__(
        self,
        document_store: DocumentStore | None = None,
        token_counter: TokenCounter | None = None,
        rag_settings: RagSettings = settings,
    ):
        self.settings = rag_settings
        self.document_store = (
            document_store or SQLiteDocumentStore()
        )
        self.token_counter = (
            token_counter or TiktokenCounter()
        )

    def build(
        self,
        query: str,
        grades: Sequence[EvidenceGrade],
    ) -> ContextBundle:
        if not query.strip():
            raise ValueError(
                "Context query cannot be empty."
            )

        if self.settings.context_max_tokens < 1:
            raise ValueError(
                "Context token budget must be positive."
            )

        if self.settings.context_max_parents < 1:
            raise ValueError(
                "Context parent limit must be positive."
            )

        candidates = self._group_relevant_grades(grades)

        ordered_candidates = sorted(
            candidates.values(),
            key=lambda candidate: (
                not candidate.directly_answers,
                -candidate.relevance_score,
                candidate.best_rank,
            ),
        )

        items = []
        total_tokens = 0

        for candidate in ordered_candidates[
            :self.settings.context_max_parents
        ]:
            remaining_tokens = (
                self.settings.context_max_tokens
                - total_tokens
            )

            if remaining_tokens <= 0:
                break

            built = self._build_item(
                candidate,
                remaining_tokens,
            )

            if built is None:
                continue

            item, token_count = built
            items.append(item)
            total_tokens += token_count

        direct_evidence_count = sum(
            item.directly_answers
            for item in items
        )

        return ContextBundle(
            query=query,
            items=tuple(items),
            total_tokens=total_tokens,
            has_direct_evidence=(
                direct_evidence_count
                >= self.settings.minimum_direct_evidence
            ),
        )

    @staticmethod
    def _group_relevant_grades(
        grades: Sequence[EvidenceGrade],
    ) -> dict[tuple[str, str], _ParentCandidate]:
        candidates = {}

        for grade in grades:
            if not grade.is_relevant:
                continue

            key = (
                grade.hit.chunk.document_id,
                grade.hit.chunk.parent_id,
            )

            candidate = candidates.setdefault(
                key,
                _ParentCandidate(),
            )
            candidate.grades.append(grade)

        return candidates

    def _build_item(
        self,
        candidate: _ParentCandidate,
        remaining_tokens: int,
    ) -> tuple[ContextItem, int] | None:
        representative = min(
            candidate.grades,
            key=lambda grade: (
                not grade.directly_answers,
                -grade.relevance_score,
                grade.hit.rank,
            ),
        )
        chunk = representative.hit.chunk

        parent = self.document_store.get_parent(
            chunk.parent_id
        )
        document = self.document_store.get_document(
            chunk.document_id
        )

        parent_text = (
            self._parent_text(parent)
            if parent is not None
            else None
        )
        text = parent_text or chunk.text
        expanded_from_parent = parent_text is not None

        original_token_count = self.token_counter.count(text)
        truncated = original_token_count > remaining_tokens

        if truncated:
            text = self.token_counter.truncate(
                text,
                remaining_tokens,
            )

        if not text.strip():
            return None

        token_count = self.token_counter.count(text)

        page_number = (
            parent.page_number
            if parent is not None
            else chunk.page_number
        )
        heading_path = (
            parent.heading_path
            if parent is not None
            else chunk.heading_path
        )

        supporting_chunk_ids = tuple(
            dict.fromkeys(
                grade.hit.chunk.chunk_id
                for grade in sorted(
                    candidate.grades,
                    key=lambda grade: grade.hit.rank,
                )
            )
        )

        return (
            ContextItem(
                parent_id=chunk.parent_id,
                document_id=chunk.document_id,
                document_title=(
                    document.title
                    if document is not None
                    else str(
                        chunk.metadata.get(
                            "document_title",
                            "Unknown document",
                        )
                    )
                ),
                text=text,
                content_type=chunk.content_type,
                source_uri=(
                    document.source_uri
                    if document is not None
                    else chunk.source_uri
                ),
                page_number=page_number,
                heading_path=heading_path,
                supporting_chunk_ids=supporting_chunk_ids,
                relevance_score=(
                    candidate.relevance_score
                ),
                directly_answers=(
                    candidate.directly_answers
                ),
                expanded_from_parent=(
                    expanded_from_parent
                ),
                truncated=truncated,
            ),
            token_count,
        )

    @staticmethod
    def _parent_text(
        parent: ParentContent,
    ) -> str | None:
        if isinstance(parent, DocumentSection):
            return parent.text

        if isinstance(parent, DocumentTable):
            return parent.markdown

        if isinstance(parent, DocumentImage):
            parts = []

            if parent.caption:
                parts.append(
                    f"Image caption: {parent.caption}"
                )

            if (
                parent.description
                and parent.description != parent.caption
            ):
                parts.append(
                    f"Image description: "
                    f"{parent.description}"
                )

            return "\n".join(parts) or None

        return None
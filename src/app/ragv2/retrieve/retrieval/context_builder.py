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
    ParsedDocument,
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
        ordered_candidates = self._diversify(
            ordered_candidates,
            key=lambda candidate: (
                candidate.grades[0].hit.chunk.document_id
            ),
        )

        items = []
        total_tokens = 0
        seen_context = set()

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

            context_key = (
                item.document_id,
                " ".join(item.text.casefold().split()),
            )

            if context_key in seen_context:
                continue

            seen_context.add(context_key)
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

    def merge(
        self,
        query: str,
        bundles: Sequence[ContextBundle],
    ) -> ContextBundle:
        """Merges retry/web context without exceeding the budget."""

        query = query.strip()

        if not query:
            raise ValueError(
                "Merged context query cannot be empty."
            )

        best_by_parent = {}

        for bundle in bundles:
            for item in bundle.items:
                key = (item.document_id, item.parent_id)
                current = best_by_parent.get(key)

                if current is None:
                    best_by_parent[key] = item
                    continue

                preferred = (
                    item
                    if (
                        self._item_priority(item)
                        > self._item_priority(current)
                    )
                    else current
                )
                information_needs = tuple(
                    dict.fromkeys(
                        (
                            *current.information_needs,
                            *item.information_needs,
                        )
                    )
                )
                best_by_parent[key] = preferred.model_copy(
                    update={
                        "information_needs": information_needs,
                    }
                )

        ordered = sorted(
            best_by_parent.values(),
            key=lambda item: (
                not item.directly_answers,
                -item.relevance_score,
                item.document_title.casefold(),
                item.page_number or 0,
            ),
        )
        ordered = self._diversify(
            ordered,
            key=lambda item: item.document_id,
        )

        items = []
        total_tokens = 0

        for item in ordered[
            :self.settings.context_max_parents
        ]:
            remaining = (
                self.settings.context_max_tokens
                - total_tokens
            )

            if remaining <= 0:
                break

            text = item.text
            token_count = self.token_counter.count(text)

            if token_count > remaining:
                text = self.token_counter.truncate(
                    text,
                    remaining,
                )
                token_count = self.token_counter.count(text)
                item = item.model_copy(
                    update={
                        "text": text,
                        "truncated": True,
                    }
                )

            if text.strip():
                items.append(item)
                total_tokens += token_count

        direct_count = sum(
            item.directly_answers
            for item in items
        )

        return ContextBundle(
            query=query,
            items=tuple(items),
            total_tokens=total_tokens,
            has_direct_evidence=(
                direct_count
                >= self.settings.minimum_direct_evidence
            ),
        )

    def build_requirements(
        self,
        query: str,
        requirements: Sequence[tuple[str, Sequence[EvidenceGrade]]],
    ) -> ContextBundle:
        """Builds compact context while reserving space for every need."""

        limit = max(1, self.settings.context_parents_per_requirement)
        bundles = []
        reserved_parents = set()

        for requirement, grades in requirements:
            bundle = self.build(requirement, grades)
            direct_items = tuple(
                item for item in bundle.items
                if item.directly_answers
            )
            unused_direct = tuple(
                item for item in direct_items
                if (item.document_id, item.parent_id)
                not in reserved_parents
            )
            selected = list(unused_direct[:limit])

            if len(selected) < limit:
                selected_keys = {
                    (item.document_id, item.parent_id)
                    for item in selected
                }
                selected.extend(
                    item
                    for item in direct_items
                    if (item.document_id, item.parent_id)
                    not in selected_keys
                )

            if len(selected) < limit:
                selected_keys = {
                    (item.document_id, item.parent_id)
                    for item in selected
                }
                selected.extend(
                    item
                    for item in bundle.items
                    if (item.document_id, item.parent_id)
                    not in selected_keys
                )

            selected = tuple(
                item.model_copy(
                    update={
                        "information_needs": tuple(
                            dict.fromkeys(
                                (*item.information_needs, requirement)
                            )
                        )
                    }
                )
                for item in selected[:limit]
            )
            reserved_parents.update(
                (item.document_id, item.parent_id)
                for item in selected
            )
            bundles.append(
                ContextBundle(
                    query=requirement,
                    items=selected,
                    total_tokens=sum(
                        self.token_counter.count(item.text)
                        for item in selected
                    ),
                    has_direct_evidence=any(
                        item.directly_answers for item in selected
                    ),
                )
            )

        return self.merge(query, bundles)

    @staticmethod
    def _item_priority(item: ContextItem) -> tuple:
        return (
            item.directly_answers,
            item.relevance_score,
            not item.truncated,
            len(item.text),
        )

    def _diversify(self, values, *, key):
        """Prefers source variety, then backfills remaining slots."""

        preferred = []
        deferred = []
        counts = {}
        preferred_limit = max(
            1,
            self.settings.context_preferred_parents_per_document,
        )

        for value in values:
            identity = key(value)
            count = counts.get(identity, 0)

            if count < preferred_limit:
                preferred.append(value)
                counts[identity] = count + 1
            else:
                deferred.append(value)

        return [*preferred, *deferred]

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

        parent_text = self._expanded_parent_text(
            parent,
            document,
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

    def _expanded_parent_text(
        self,
        parent: ParentContent | None,
        document: ParsedDocument | None,
    ) -> str | None:
        """Rejoins short parser fragments that belong to one page block.

        PDF parsers often emit titles, author lists, addresses, or OCR lines
        as separate parents. A relevant child can therefore be correct while
        lacking enough surrounding meaning for generation. Only short,
        adjacent sections with the same page and heading are joined here;
        normal prose, tables, and images keep their original boundaries.
        """

        text = (
            self._parent_text(parent)
            if parent is not None
            else None
        )

        if (
            not isinstance(parent, DocumentSection)
            or document is None
            or text is None
            or self.token_counter.count(text)
            > self.settings.context_fragment_max_tokens
        ):
            return text

        sections = document.sections
        parent_index = next(
            (
                index
                for index, section in enumerate(sections)
                if section.section_id == parent.section_id
            ),
            None,
        )

        if parent_index is None:
            return text

        related = [parent]

        for direction in (-1, 1):
            for distance in range(
                1,
                self.settings.context_fragment_window + 1,
            ):
                index = parent_index + direction * distance

                if index < 0 or index >= len(sections):
                    break

                section = sections[index]

                if (
                    section.page_number != parent.page_number
                    or section.heading_path != parent.heading_path
                    or self.token_counter.count(section.text)
                    > self.settings.context_fragment_max_tokens
                ):
                    break

                related.append(section)

        related.sort(key=sections.index)

        if len(related) < 2:
            return text

        combined = "\n".join(
            section.text.strip()
            for section in related
            if section.text.strip()
        )

        if (
            not combined
            or self.token_counter.count(combined)
            > self.settings.context_fragment_group_max_tokens
        ):
            return text

        return combined

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

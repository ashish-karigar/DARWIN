import json
from dataclasses import dataclass

from app.ragv2.contracts import (
    Citation,
    ContextBundle,
)


@dataclass(frozen=True, slots=True)
class CitationContext:
    prompt_context: str
    citations: tuple[Citation, ...]


class CitationBuilder:
    """Converts context into traceable, JSON-isolated evidence records."""

    def build(
        self,
        context: ContextBundle,
    ) -> CitationContext:
        citations = []
        evidence_blocks = []

        for index, item in enumerate(
            context.items,
            start=1,
        ):
            citation_id = f"S{index}"

            citation = Citation(
                citation_id=citation_id,
                document_id=item.document_id,
                document_title=item.document_title,
                source_uri=item.source_uri,
                page_number=item.page_number,
                heading_path=item.heading_path,
                parent_id=item.parent_id,
                supporting_chunk_ids=(
                    item.supporting_chunk_ids
                ),
            )
            citations.append(citation)

            evidence_blocks.append(
                self._format_evidence(
                    citation,
                    item.text,
                    item.information_needs,
                )
            )

        return CitationContext(
            prompt_context="\n".join(evidence_blocks),
            citations=tuple(citations),
        )

    @staticmethod
    def _format_evidence(
        citation: Citation,
        text: str,
        information_needs: tuple[str, ...] = (),
    ) -> str:
        return json.dumps(
            {
                "citation": f"[{citation.citation_id}]",
                "document": citation.document_title,
                "source": citation.source_uri,
                "page": citation.page_number,
                "heading": list(citation.heading_path),
                "information_needs": list(information_needs),
                "content": text,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )

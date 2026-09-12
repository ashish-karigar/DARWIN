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
    """Converts retrieved context into numbered, traceable evidence."""

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
                )
            )

        return CitationContext(
            prompt_context="\n\n".join(evidence_blocks),
            citations=tuple(citations),
        )

    @staticmethod
    def _format_evidence(
        citation: Citation,
        text: str,
    ) -> str:
        metadata = [
            f"[{citation.citation_id}]",
            f"Document: {citation.document_title}",
            f"Source: {citation.source_uri}",
        ]

        if citation.page_number is not None:
            metadata.append(
                f"Page: {citation.page_number}"
            )

        if citation.heading_path:
            metadata.append(
                "Heading: "
                + " > ".join(citation.heading_path)
            )

        metadata.append(f"Evidence:\n{text}")

        return "\n".join(metadata)
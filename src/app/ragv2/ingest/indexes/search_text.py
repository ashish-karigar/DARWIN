from app.ragv2.contracts import Chunk


def build_search_text(chunk: Chunk) -> str:
    """Adds lightweight parent context to a child's indexed text."""

    parts = []

    document_title = str(
        chunk.metadata.get("document_title", "")
    ).strip()

    if document_title:
        parts.append(
            f"Document: {document_title}"
        )

    heading = " > ".join(chunk.heading_path).strip()

    if heading:
        parts.append(
            f"Section: {heading}"
        )

    parts.append(
        f"Content: {chunk.text}"
    )

    return "\n".join(parts)
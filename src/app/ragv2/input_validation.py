from collections.abc import Sequence

from app.ragv2.config import RagSettings, settings


def validate_query(
    query: str,
    *,
    rag_settings: RagSettings = settings,
) -> str:
    """Normalize a user query and reject resource-exhaustion inputs."""

    normalized = query.strip()

    if not normalized:
        raise ValueError("RAG question cannot be empty.")

    if len(normalized) > rag_settings.maximum_query_characters:
        raise ValueError(
            "RAG question exceeds the maximum length of "
            f"{rag_settings.maximum_query_characters} characters."
        )

    return normalized


def validate_conversation_context(
    messages: Sequence[str],
    *,
    rag_settings: RagSettings = settings,
) -> tuple[str, ...]:
    """Bound history before it reaches retrieval or an external model."""

    normalized = tuple(
        message.strip()
        for message in messages
        if message.strip()
    )

    if len(normalized) > rag_settings.maximum_conversation_messages:
        raise ValueError(
            "Conversation context exceeds the maximum of "
            f"{rag_settings.maximum_conversation_messages} messages."
        )

    total_characters = sum(len(message) for message in normalized)
    if total_characters > rag_settings.maximum_conversation_characters:
        raise ValueError(
            "Conversation context exceeds the maximum length of "
            f"{rag_settings.maximum_conversation_characters} characters."
        )

    return normalized

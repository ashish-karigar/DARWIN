import re


_PUNCTUATION_RUN = re.compile(r"(?:\s*[.…]{2,}\s*)+")


def clean_response(text: str) -> str:
    """Remove model artifacts before a response reaches the terminal or TTS."""
    cleaned = text.strip()
    cleaned = _PUNCTUATION_RUN.sub(" ", cleaned)
    cleaned = re.sub(r"([!?;,])\1+", r"\1", cleaned)
    cleaned = re.sub(r"\s+([,.!?])", r"\1", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(
        r"^(?:sure|certainly|okay|of course)[,.!]?\s+(?:let me\s+)?"
        r"(?=(?:which|what|where|when|who|how)\b)",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    if not re.search(r"[A-Za-z0-9]", cleaned):
        raise RuntimeError("The model returned only punctuation.")
    return cleaned

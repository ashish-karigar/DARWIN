from typing import Protocol

import tiktoken

class TokenCounter(Protocol):
    def count(self, text: str) -> int:
        """Return the approximate number of model tokens."""
        ...

    def truncate(
            self,
            text: str,
            maximum_tokens: int,
    ) -> str:
        ...

class TiktokenCounter:
    """Deterministic token estimator used to control chunk size."""

    def __init__(self, encoding_name: str = "cl100k_base"):
        self.encoding_name = encoding_name
        self._encoding = tiktoken.get_encoding(encoding_name)

    def count(self, text: str) -> int:
        return len(
            self._encoding.encode(
                text,
                disallowed_special=()
            )
        )

    def truncate(
            self,
            text: str,
            maximum_tokens: int,
    ) -> str:
        if maximum_tokens < 0:
            raise ValueError(
                "Maximum token count cannot be negative."
            )

        if maximum_tokens == 0:
            return ""

        tokens = self._encoding.encode(
            text,
            disallowed_special=(),
        )

        if len(tokens) <= maximum_tokens:
            return text

        return self._encoding.decode(
            tokens[:maximum_tokens]
        )
from collections.abc import Sequence
from math import ceil
import re
import unicodedata


def percentage(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def percentile(values: Sequence[float], fraction: float) -> float:
    if not values:
        return 0.0

    ordered = sorted(values)
    index = max(0, ceil(len(ordered) * fraction) - 1)
    return round(ordered[index], 4)


def contains_required_terms(
    answer: str,
    required_terms: Sequence[str],
) -> bool:
    normalized = normalize_text(answer)
    return all(
        normalize_text(term) in normalized
        for term in required_terms
    )


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = "".join(
        "-" if unicodedata.category(character) == "Pd" else character
        for character in value
    )
    value = re.sub(r"(?<=\d)\s+(?=[kmb]\b)", "", value)
    return " ".join(value.split())


def fact_recall(
    answer: str,
    required_groups: Sequence[Sequence[str]],
) -> float:
    """Scores how many required facts have one accepted expression."""

    if not required_groups:
        return 100.0

    normalized = normalize_text(answer)
    matched = sum(
        any(normalize_text(term) in normalized for term in group)
        for group in required_groups
    )
    return percentage(matched, len(required_groups))


def missing_fact_groups(
    answer: str,
    required_groups: Sequence[Sequence[str]],
) -> tuple[tuple[str, ...], ...]:
    """Returns expected fact expressions absent from an answer."""

    normalized = normalize_text(answer)
    return tuple(
        tuple(group)
        for group in required_groups
        if not any(
            normalize_text(term) in normalized
            for term in group
        )
    )


def excludes_forbidden_terms(
    answer: str,
    forbidden_terms: Sequence[str],
) -> bool:
    normalized = normalize_text(answer)
    return not any(
        normalize_text(term) in normalized
        for term in forbidden_terms
    )


def source_matches(
    source_uri: str,
    expected_suffixes: Sequence[str],
) -> bool:
    normalized = source_uri.casefold()
    return any(
        normalized.endswith(suffix.casefold())
        for suffix in expected_suffixes
    )


def source_coverage(
    source_uris: Sequence[str],
    required_suffixes: Sequence[str],
) -> float:
    """Measures how many individually required sources were present."""

    if not required_suffixes:
        return 100.0

    matched = sum(
        any(source_matches(uri, (suffix,)) for uri in source_uris)
        for suffix in required_suffixes
    )
    return percentage(matched, len(required_suffixes))

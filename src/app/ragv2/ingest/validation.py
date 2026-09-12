from dataclasses import dataclass

from app.ragv2.contracts import ParsedDocument


ASSISTANCE_THRESHOLD = 0.70


@dataclass(frozen=True, slots=True)
class ParseQualityReport:
    score: float
    issues: tuple[str, ...]

    @property
    def needs_assistance(self) -> bool:
        return self.score <= ASSISTANCE_THRESHOLD


def assess_parse_quality(
    document: ParsedDocument,
) -> ParseQualityReport:
    issues: list[str] = []
    penalty = 0.0

    text_blocks = [
        section.text.strip()
        for section in document.sections
        if section.text.strip()
    ]
    table_blocks = [
        table.markdown.strip()
        for table in document.tables
        if table.markdown.strip()
    ]

    all_blocks = text_blocks + table_blocks
    total_characters = sum(len(block) for block in all_blocks)

    if total_characters < 100:
        issues.append("Very little content was extracted.")
        penalty += 0.25

    page_count = int(document.metadata.get("page_count") or 0)
    if page_count and total_characters / page_count < 100:
        issues.append("Extracted content is unusually sparse for the page count.")
        penalty += 0.30

    normalized_blocks = [
        " ".join(block.casefold().split())
        for block in all_blocks
    ]

    if normalized_blocks:
        duplicate_count = (
            len(normalized_blocks) - len(set(normalized_blocks))
        )
        duplicate_ratio = duplicate_count / len(normalized_blocks)

        if duplicate_ratio > 0.25:
            issues.append("The parsed document contains excessive repetition.")
            penalty += 0.35

    combined_text = " ".join(all_blocks)
    if combined_text:
        replacement_ratio = combined_text.count("�") / len(combined_text)

        if replacement_ratio > 0.005:
            issues.append("The parsed text contains decoding corruption.")
            penalty += 0.30

    unexplained_images = sum(
        image.description is None and image.caption is None
        for image in document.images
    )

    if unexplained_images:
        issues.append(
            f"{unexplained_images} image(s) have no description or caption."
        )
        penalty += 0.15

    score = round(max(0.0, 1.0 - penalty), 3)

    return ParseQualityReport(
        score=score,
        issues=tuple(issues),
    )
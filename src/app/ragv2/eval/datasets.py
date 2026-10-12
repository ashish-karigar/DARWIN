import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ragv2.contracts import QueryStrategy


class EvaluationCase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    question: str = Field(min_length=1)
    should_answer: bool
    expected_source_suffixes: tuple[str, ...] = ()
    required_terms: tuple[str, ...] = ()
    required_term_groups: tuple[tuple[str, ...], ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    required_citation_source_suffixes: tuple[str, ...] = ()
    conversation_context: tuple[str, ...] = ()
    expected_strategy: QueryStrategy | None = None
    maximum_latency_seconds: float | None = Field(
        default=None,
        gt=0,
    )
    tags: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_expectations(self) -> "EvaluationCase":
        if self.should_answer and not self.expected_source_suffixes:
            raise ValueError(
                "Answerable cases require at least one expected source."
            )

        if not self.should_answer and (
            self.required_terms or self.required_term_groups
        ):
            raise ValueError(
                "No-answer cases cannot require answer facts."
            )

        if any(not group for group in self.required_term_groups):
            raise ValueError(
                "Required term groups cannot be empty."
            )
        return self

    @property
    def fact_groups(self) -> tuple[tuple[str, ...], ...]:
        """Returns facts where any phrase in each group is acceptable."""

        return (
            *((term,) for term in self.required_terms),
            *self.required_term_groups,
        )

    @property
    def required_citation_sources(self) -> tuple[str, ...]:
        return (
            self.required_citation_source_suffixes
            or self.expected_source_suffixes
        )


class EvaluationQualityGates(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_success_min_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )
    retrieval_source_recall_min_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )
    retrieval_answerability_min_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )
    strategy_accuracy_min_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )
    answer_accuracy_min_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )
    answer_completeness_min_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )
    citation_recall_min_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )
    no_answer_rejection_min_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )
    false_abstention_max_percent: float = Field(
        default=100.0,
        ge=0.0,
        le=100.0,
    )
    latency_budget_pass_min_percent: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
    )
    p95_latency_max_seconds: float | None = Field(
        default=None,
        gt=0.0,
    )


class EvaluationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    cases: tuple[EvaluationCase, ...]
    quality_gates: EvaluationQualityGates = Field(
        default_factory=EvaluationQualityGates
    )

    @model_validator(mode="after")
    def validate_cases(self) -> "EvaluationDataset":
        identifiers = [case.case_id for case in self.cases]

        if not identifiers:
            raise ValueError("Evaluation dataset cannot be empty.")

        if len(identifiers) != len(set(identifiers)):
            raise ValueError("Evaluation case IDs must be unique.")

        return self

    def select(
        self,
        *,
        case_ids: tuple[str, ...] = (),
        tags: tuple[str, ...] = (),
        limit: int | None = None,
    ) -> "EvaluationDataset":
        """Returns a smaller dataset for focused, low-cost test runs."""

        requested_ids = set(case_ids)
        requested_tags = set(tags)
        selected = tuple(
            case
            for case in self.cases
            if (
                not requested_ids
                or case.case_id in requested_ids
            )
            and (
                not requested_tags
                or requested_tags.intersection(case.tags)
            )
        )

        if limit is not None:
            selected = selected[:limit]

        if requested_ids:
            missing = requested_ids.difference(
                case.case_id for case in selected
            )
            if missing:
                raise ValueError(
                    "Unknown or excluded evaluation case IDs: "
                    + ", ".join(sorted(missing))
                )

        if not selected:
            raise ValueError(
                "Evaluation filters did not select any cases."
            )

        return self.model_copy(update={"cases": selected})


def load_dataset(path: str | Path) -> EvaluationDataset:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return EvaluationDataset.model_validate(payload)

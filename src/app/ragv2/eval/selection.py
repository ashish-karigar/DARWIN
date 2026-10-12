"""Select focused case sets from previous benchmark reports."""

import json
from pathlib import Path


def failed_case_ids_from_report(path: str | Path) -> tuple[str, ...]:
    """Selects cases that need another run from a saved report."""

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("Evaluation report does not contain a cases list.")

    failed_ids = []
    for case in cases:
        if not isinstance(case, dict) or not case.get("case_id"):
            raise ValueError("Evaluation report contains an invalid case.")

        if _case_needs_rerun(case):
            failed_ids.append(str(case["case_id"]))

    if not failed_ids:
        raise ValueError("The evaluation report has no failed cases.")

    return tuple(failed_ids)


def _case_needs_rerun(case: dict) -> bool:
    should_answer = bool(case.get("should_answer"))
    common_failure = bool(
        case.get("error")
        or case.get("provider_failure_count", 0)
        or case.get("fallback_used_count", 0)
        or case.get("schema_invalid_count", 0)
        or case.get("strategy_correct") is False
        or case.get("latency_budget_passed") is False
    )

    if common_failure:
        return True

    if should_answer:
        return bool(
            case.get("answer_correct") is not True
            or case.get("grounded") is not True
            or case.get("verification_passed") is not True
            or (case.get("citation_recall") or 0) < 100
        )

    return bool(
        case.get("abstention_correct") is not True
        or case.get("false_answer")
    )

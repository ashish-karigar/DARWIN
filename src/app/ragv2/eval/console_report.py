"""Human-readable terminal rendering for RAG evaluation reports."""

from collections.abc import Iterable, Sequence
from pathlib import Path
from textwrap import wrap

from app.ragv2.eval.report import CaseResult, EvaluationReport


def render_console_report(
    report: EvaluationReport,
    output_path: Path,
) -> str:
    """Renders summary, case results, and failures as terminal tables."""

    sections = [
        _render_heading(report),
        _render_summary(report, output_path),
        _render_cases(report.cases, retrieval_only=report.retrieval_only),
        # _render_query_plans(report.cases),
        # _render_pipeline_routes(report.cases),
        # _render_stage_results(report.cases),
    ]

    # failures = tuple(
    #     case
    #     for case in report.cases
    #     if _case_status(case, retrieval_only=report.retrieval_only) != "PASS"
    # )
    # if failures:
    #     sections.append(_render_failures(failures))

    # if report.category_results:
    #     sections.append(_render_categories(report.category_results))

    return "\n\n".join(section for section in sections if section)


def _render_heading(report: EvaluationReport) -> str:
    state = "STOPPED EARLY" if report.terminated_early else "COMPLETED"
    return f"RAG benchmark: {state}"


def _render_summary(
    report: EvaluationReport,
    output_path: Path,
) -> str:
    failed_gates = (
        ", ".join(report.failed_quality_gates)
        if report.failed_quality_gates
        else "none"
    )
    rows = [
        ("Cases executed", f"{report.completed_case_count}/{report.case_count}"),
        ("Quality gates", "PASS" if report.passed_quality_gates else "FAIL"),
        ("Failed gates", failed_gates),
        ("Answer accuracy", _percent(report.answer_required_term_accuracy_percent)),
        ("Answer completeness", _percent(report.answer_completeness_percent)),
        ("Retrieval source recall", _percent(report.retrieval_source_recall_percent)),
        ("Retrieval answerability", _percent(report.retrieval_answerability_percent)),
        ("Citation recall", _percent(report.citation_recall_percent)),
        ("No-answer rejection", _percent(report.no_answer_rejection_percent)),
        ("False abstentions", _percent(report.false_abstention_rate_percent)),
        ("Average latency", _seconds(report.average_latency_seconds)),
        ("P95 latency", _seconds(report.p95_latency_seconds)),
        ("Provider failures", str(report.provider_failure_count)),
        ("Fallbacks used", str(report.fallback_used_count)),
        ("Schema repairs", str(report.schema_invalid_count)),
    ]
    if report.termination_reason:
        rows.append(("Stopped because", report.termination_reason))
    rows.append(("Detailed JSON", str(output_path)))

    return "Summary\n" + _table(
        ("Metric", "Result"),
        rows,
        max_widths=(24, 88),
    )


def _render_cases(
    cases: Sequence[CaseResult],
    *,
    retrieval_only: bool,
) -> str:
    rows = []
    for case in cases:
        status = _case_status(case, retrieval_only=retrieval_only)
        rows.append(
            (
                case.case_id,
                status,
                case.query_strategy or "-",
                case.retrieval_rank if case.retrieval_rank is not None else "-",
                _yes_no(case.answer_correct),
                _yes_no(case.grounded),
                _percent(case.citation_recall),
                _yes_no(case.verification_passed),
                _seconds(case.latency_seconds),
                _provider_summary(case),
                _failure_reason(case) if status != "PASS" else "-",
            )
        )

    return "Case results\n" + _table(
        (
            "Case",
            "Status",
            "Strategy",
            "Hit",
            "Answer",
            "Ground",
            "Citations",
            "Verify",
            "Latency",
            "Model calls",
            "Reason for failure",
        ),
        rows,
        max_widths=(30, 14, 11, 5, 7, 7, 9, 7, 9, 20, 60),
    )


def _render_query_plans(cases: Sequence[CaseResult]) -> str:
    rows = []

    for case in cases:
        if not case.query_strategy:
            continue

        queries = " | ".join(case.planned_queries) or case.question
        unanswered = " | ".join(case.unanswered_queries) or "none"
        rows.append(
            (
                case.case_id,
                case.query_strategy,
                queries,
                unanswered,
            )
        )

    if not rows:
        return ""

    return "Query plans\n" + _table(
        ("Case", "Strategy", "Retrieval queries", "Unanswered"),
        rows,
        max_widths=(30, 11, 72, 50),
    )


def _render_pipeline_routes(cases: Sequence[CaseResult]) -> str:
    rows = tuple(
        (case.case_id, _pipeline_flow(case))
        for case in cases
        if case.query_strategy or case.route_history or case.error
    )

    if not rows:
        return ""

    return "Pipeline routes\n" + _table(
        ("Case", "Flow"),
        rows,
        max_widths=(30, 100),
    )


def _render_stage_results(cases: Sequence[CaseResult]) -> str:
    """Renders the pipeline's decision flow, one row per stage, timed.

    This is the source of truth for which stages ran, what each one
    produced, and how long it took -- so a slow case can be diagnosed
    from this table alone. Per-hit retrieval detail and per-item context
    text still live in the JSON output, not here, since they add no
    signal at a glance.
    """

    sections = []

    for case in cases:
        providers = _providers_by_schema(case)
        retrieval_result, ranking_result, grading_result = (
            _retrieval_stage_summaries(case.retrieval_details)
        )
        rewrite_seconds = _model_call_seconds(case, "RewriteDraft")
        generation_seconds = _model_call_seconds(case, "AnswerDraft")
        verification_seconds = _model_call_seconds(case, "VerificationDraft")

        rows: list[tuple[str, str, str]] = [
            ("Input", case.question, "-"),
            (
                "Routing & strategy",
                _routing_strategy_label(case, providers),
                _seconds(case.query_analysis_seconds),
            ),
            (
                "Retrieval",
                retrieval_result,
                _seconds(case.hybrid_retrieval_seconds),
            ),
            ("Ranking", ranking_result, _seconds(case.reranking_seconds)),
            (
                "Evidence grading",
                f"{grading_result}; coverage={_coverage_label(case)}",
                _seconds(case.grading_seconds),
            ),
            (
                "Context assembly",
                _context_label(case),
                _seconds(case.context_build_seconds),
            ),
        ]

        if "rewrite" in case.route_history:
            rows.append(
                (
                    "Rewrite",
                    " | ".join(case.rewritten_queries) or "completed",
                    _seconds(rewrite_seconds),
                )
            )
        if "retrieve_correction" in case.route_history:
            (
                correction_retrieval,
                correction_ranking,
                correction_grading,
            ) = _retrieval_stage_summaries(case.correction_details)
            rows.append(
                (
                    "Corrected retrieval",
                    f"completed for {len(case.correction_targets)} need(s); "
                    f"retrieval: {correction_retrieval}; "
                    f"ranking: {correction_ranking}; "
                    f"grading: {correction_grading}",
                    _seconds(case.correction_seconds),
                )
            )

        rows.append(
            (
                "LLM generation",
                _generation_label(case, providers),
                _seconds(generation_seconds),
            )
        )
        rows.append(("Citations", _citations_label(case), "-"))
        rows.append(
            (
                "Verification",
                _verification_label(case, providers),
                _seconds(verification_seconds),
            )
        )
        rows.append(
            (
                "Finalize",
                f"grounded={_yes_no(case.grounded)}; "
                f"abstained={_yes_no(case.answer_abstained)}; "
                f"status={_case_status(case)}",
                "-",
            )
        )

        known_seconds = sum(
            value
            for value in (
                case.query_analysis_seconds,
                case.hybrid_retrieval_seconds,
                case.reranking_seconds,
                case.grading_seconds,
                case.context_build_seconds,
                rewrite_seconds,
                case.correction_seconds,
                generation_seconds,
                verification_seconds,
            )
            if value is not None
        )
        overhead = (
            round(case.latency_seconds - known_seconds, 4)
            if case.latency_seconds is not None
            else None
        )
        if overhead is not None and overhead > 0.05:
            rows.append(
                (
                    "Overhead",
                    "orchestration glue not covered by a timed stage above "
                    "(citation building, safety checks, framework overhead)",
                    _seconds(overhead),
                )
            )
        rows.append(("Total", "end-to-end case latency", _seconds(case.latency_seconds)))

        sections.append(
            f"Stage results: {case.case_id}\n"
            + _table(
                ("Stage", "Result", "Time taken"),
                tuple(rows),
                max_widths=(20, 85, 12),
            )
        )

    return "\n\n".join(sections)


def _routing_label(providers: dict[str, list[str]]) -> str:
    routing_provider = _provider_label(providers, "QueryDecision")
    return f"model{routing_provider}" if routing_provider else "deterministic"


def _routing_strategy_label(
    case: CaseResult,
    providers: dict[str, list[str]],
) -> str:
    routing = _routing_label(providers)
    strategy = case.query_strategy or "unknown"

    if strategy == "decompose":
        detail = "; sub-questions: " + (
            _numbered(case.planned_queries) or "not produced"
        )
    elif strategy == "step_back":
        detail = f"; step-back query: {case.step_back_query or 'not produced'}"
    elif case.standalone_query and case.standalone_query != case.question:
        detail = f"; standalone query: {case.standalone_query}"
    else:
        detail = ""

    return f"{routing}; strategy={strategy}{detail}"


def _retrieval_stage_summaries(
    details: Sequence[dict[str, object]],
) -> tuple[str, str, str]:
    """Combines every sub-query's hits into one summary per stage.

    Returns the (retrieval, ranking, grading) result strings shared by
    both the main and corrective retrieval rows.
    """

    if not details:
        return "not run", "not run", "not run"

    retrieval_parts = []
    ranking_parts = []
    grading_parts = []
    for index, detail in enumerate(details, start=1):
        hits = detail.get("hits", ())
        relevant_count = sum(1 for hit in hits if hit.get("relevant"))
        top_score = hits[0].get("score", "-") if hits else "-"
        label = f"Q{index}"
        retrieval_parts.append(
            f"{label}: {detail.get('candidate_count', 0)} candidates"
        )
        ranking_parts.append(f"{label}: top score {top_score}")
        grading_parts.append(f"{label}: {relevant_count}/{len(hits)} relevant")

    return (
        "; ".join(retrieval_parts),
        "; ".join(ranking_parts),
        "; ".join(grading_parts),
    )


def _model_call_seconds(case: CaseResult, schema: str) -> float:
    return sum(
        float(event.get("elapsed_seconds") or 0.0)
        for event in case.model_calls
        if event.get("schema") == schema
    )


def _coverage_label(case: CaseResult) -> str:
    if case.retrieval_answerable:
        return "complete"
    return "missing: " + (" | ".join(case.unanswered_queries) or "unknown")


def _context_label(case: CaseResult) -> str:
    sources = ", ".join(case.context_sources) or "none"
    return (
        f"{case.context_item_count} item(s), "
        f"{case.context_token_count} tokens from {sources}"
    )


def _generation_label(
    case: CaseResult,
    providers: dict[str, list[str]],
) -> str:
    if not case.answer_text:
        return "not run"
    provider = _provider_label(providers, "AnswerDraft").lstrip(":")
    return f"{provider}: {case.answer_text}"


def _citations_label(case: CaseResult) -> str:
    return ", ".join(
        f"{citation.citation_id}: {citation.document_title}"
        + (
            f" p.{citation.page_number}"
            if citation.page_number is not None
            else ""
        )
        for citation in case.citations
    ) or "none"


def _verification_label(
    case: CaseResult,
    providers: dict[str, list[str]],
) -> str:
    verification_provider = _provider_label(providers, "VerificationDraft")
    mode = (
        f"semantic{verification_provider}"
        if verification_provider
        else "deterministic"
    )
    return f"{mode}; supported={_yes_no(case.verification_passed)}"


def _numbered(values: Sequence[str]) -> str:
    return " | ".join(
        f"{index}. {value}"
        for index, value in enumerate(values, start=1)
    )


def _pipeline_flow(case: CaseResult) -> str:
    providers = _providers_by_schema(case)
    strategy = case.query_strategy or "unknown"
    analyzer = _provider_label(providers, "QueryDecision")
    analyze = f"Analyze[{strategy}{analyzer}]"
    stages = ["Question", analyze]
    occurrences: dict[str, int] = {}

    labels = {
        "retrieve": (
            f"Retrieve[{case.retrieval_trace_count or len(case.planned_queries)} "
            "queries]"
        ),
        "rewrite": "Rewrite",
        "retrieve_correction": "Corrective retrieval",
        "generate": "Generate",
        "regenerate": "Regenerate",
        "verify": "Verify",
        "abstain": "Abstain",
        "finalize": "Finalize",
    }
    schemas = {
        "rewrite": "RewriteDraft",
        "generate": "AnswerDraft",
        "regenerate": "AnswerDraft",
        "verify": "VerificationDraft",
    }

    for route in case.route_history:
        label = labels.get(route, route.replace("_", " ").title())
        schema = schemas.get(route)

        if schema:
            occurrence = occurrences.get(schema, 0)
            provider = _provider_label(
                providers,
                schema,
                occurrence=occurrence,
            )
            occurrences[schema] = occurrence + 1
            label += provider

        stages.append(label)

    if case.error:
        stages.append("Error")
    elif case.answer_abstained:
        stages.append("No answer")
    elif case.answer_text:
        stages.append("Answer")

    return " -> ".join(stages)


def _providers_by_schema(case: CaseResult) -> dict[str, list[str]]:
    providers: dict[str, list[str]] = {}

    for event in case.model_calls:
        schema = str(event.get("schema", ""))
        provider = str(event.get("provider", ""))
        if schema and provider:
            providers.setdefault(schema, []).append(provider)

    return providers


def _provider_label(
    providers: dict[str, list[str]],
    schema: str,
    *,
    occurrence: int = 0,
) -> str:
    values = providers.get(schema, [])
    if not values:
        return ""

    provider = values[min(occurrence, len(values) - 1)]
    return f":{provider}"


def _render_failures(cases: Sequence[CaseResult]) -> str:
    rows = tuple((case.case_id, _failure_reason(case)) for case in cases)
    return "Needs attention\n" + _table(
        ("Case", "Reason"),
        rows,
        max_widths=(30, 88),
    )


def _render_categories(
    categories: dict[str, dict[str, float | int | None]],
) -> str:
    rows = []
    for name, metrics in sorted(categories.items()):
        rows.append(
            (
                name,
                metrics.get("case_count", 0),
                _percent(metrics.get("answer_accuracy_percent")),
                _percent(metrics.get("retrieval_source_recall_percent")),
                _percent(metrics.get("strategy_accuracy_percent")),
                _seconds(metrics.get("average_latency_seconds")),
            )
        )

    return "Category results\n" + _table(
        ("Category", "Cases", "Answer", "Retrieval", "Strategy", "Avg latency"),
        rows,
        max_widths=(24, 7, 9, 10, 10, 12),
    )


def _case_status(
    case: CaseResult,
    *,
    retrieval_only: bool = False,
) -> str:
    if case.error == "SkippedAfterProviderFailure":
        return "SKIPPED"
    if case.error:
        return "ERROR"
    if case.provider_failure_count:
        return "PROVIDER FAIL"
    if case.fallback_used_count:
        return "FALLBACK"
    if case.schema_invalid_count:
        return "REPAIRED"

    common_passed = (
        case.strategy_correct is not False
        and case.latency_budget_passed is not False
    )
    if retrieval_only:
        if case.should_answer:
            passed = (
                case.retrieval_rank is not None
                and case.retrieval_answerable
                and (
                    case.retrieval_source_recall is None
                    or case.retrieval_source_recall >= 100
                )
                and common_passed
            )
        else:
            passed = not case.retrieval_answerable and common_passed
        return "PASS" if passed else "FAIL"

    if case.should_answer:
        passed = (
            case.answer_correct is True
            and case.grounded is True
            and case.verification_passed is True
            and (case.citation_recall is None or case.citation_recall >= 100)
            and common_passed
        )
        return "PASS" if passed else "FAIL"

    passed = case.abstention_correct is True and common_passed
    if passed:
        return "PASS"
    return "FALSE ANSWER" if case.false_answer else "FAIL"


def _failure_reason(case: CaseResult) -> str:
    reasons = []
    if case.error_message:
        reasons.append(case.error_message)
    elif case.error:
        reasons.append(case.error)

    if case.provider_failure_count:
        reasons.append(f"{case.provider_failure_count} provider failure(s)")
    if case.fallback_used_count:
        reasons.append(f"{case.fallback_used_count} fallback call(s)")
    if case.schema_invalid_count:
        reasons.append(f"{case.schema_invalid_count} schema repair(s)")
    if case.false_abstention:
        reasons.append("answerable question was abstained")
    if case.false_answer:
        reasons.append("unanswerable question received an answer")
    if case.strategy_correct is False:
        reasons.append("unexpected query strategy")
    if case.latency_budget_passed is False:
        reasons.append(f"latency exceeded budget ({_seconds(case.latency_seconds)})")
    if case.missing_fact_groups:
        expected = ", ".join(group[0] for group in case.missing_fact_groups)
        reasons.append(f"missing required facts: {expected}")
    if case.unsupported_claims and case.should_answer:
        reasons.append("unsupported: " + "; ".join(case.unsupported_claims))
    if case.verification_unsupported_claims:
        reasons.append(
            "verification rejected: "
            + "; ".join(case.verification_unsupported_claims)
        )
    if case.verification_contradicted_claims:
        reasons.append(
            "contradicted: "
            + "; ".join(case.verification_contradicted_claims)
        )

    return "; ".join(reasons) or "one or more quality checks failed"


def _provider_summary(case: CaseResult) -> str:
    if not case.provider_call_counts:
        return "-"
    return ", ".join(
        f"{provider}:{count}"
        for provider, count in case.provider_call_counts
    )


def _yes_no(value: bool | None) -> str:
    if value is None:
        return "-"
    return "yes" if value else "no"


def _percent(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.2f}%"


def _seconds(value: float | int | None) -> str:
    if value is None:
        return "-"
    return f"{float(value):.2f}s"


def _table(
    headers: Sequence[str],
    rows: Iterable[Sequence[object]],
    *,
    max_widths: Sequence[int],
) -> str:
    """Builds a dependency-free table with wrapped cells."""

    string_rows = [tuple(str(cell) for cell in row) for row in rows]
    all_rows = [tuple(headers), *string_rows]
    widths = tuple(
        min(
            max_widths[index],
            max(len(row[index]) for row in all_rows),
        )
        for index in range(len(headers))
    )
    separator = "+-" + "-+-".join("-" * width for width in widths) + "-+"

    def render_row(row: Sequence[str]) -> list[str]:
        cells = [
            wrap(cell, width=width, break_long_words=True) or [""]
            for cell, width in zip(row, widths)
        ]
        height = max(len(cell) for cell in cells)
        return [
            "| "
            + " | ".join(
                (cell[line] if line < len(cell) else "").ljust(width)
                for cell, width in zip(cells, widths)
            )
            + " |"
            for line in range(height)
        ]

    output = [separator, *render_row(tuple(headers)), separator]
    for row in string_rows:
        output.extend(render_row(row))
    output.append(separator)
    return "\n".join(output)

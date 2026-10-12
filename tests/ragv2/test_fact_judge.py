from app.ragv2.eval.fact_judge import (
    FactCoverageDraft,
    FactCoverageJudge,
    FactCoverageJudgment,
    StructuredLLMFactCoverageProvider,
)


class RecordingFactCoverageProvider:
    """Captures exactly what FactCoverageJudge.coverage() sends it."""

    def __init__(self, covered):
        self.covered = covered
        self.calls = []

    def judge(self, answer, facts):
        self.calls.append((answer, tuple(facts)))
        return self.covered


class FakeModelRunner:
    """Stands in for the StructuredModelRunner the provider normally owns."""

    def __init__(self, draft: FactCoverageDraft):
        self.draft = draft
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return self.draft


def make_provider(draft: FactCoverageDraft) -> StructuredLLMFactCoverageProvider:
    provider = StructuredLLMFactCoverageProvider.__new__(
        StructuredLLMFactCoverageProvider
    )
    provider.model = FakeModelRunner(draft)
    return provider


def test_matches_judgments_by_position_when_counts_line_up():
    """One judgment per fact should zip by order, whatever the model's

    reported fact_index says -- this is the real bug this test guards:
    a model that answers 0-indexed instead of the prompt's 1-indexed
    numbering must not silently drop the last fact.
    """

    draft = FactCoverageDraft(
        judgments=(
            FactCoverageJudgment(
                fact_index=0, covered=True, reason="Matches fact one."
            ),
            FactCoverageJudgment(
                fact_index=1, covered=True, reason="Matches fact two."
            ),
            FactCoverageJudgment(
                fact_index=2, covered=False, reason="Missing fact three."
            ),
            FactCoverageJudgment(
                fact_index=3, covered=True, reason="Matches fact four."
            ),
        )
    )
    provider = make_provider(draft)

    covered = provider.judge(
        "answer text",
        ["fact one", "fact two", "fact three", "fact four"],
    )

    assert covered == (True, True, False, True)


def test_matches_judgments_correctly_when_1_indexed_as_prompted():
    draft = FactCoverageDraft(
        judgments=(
            FactCoverageJudgment(fact_index=1, covered=True, reason="ok"),
            FactCoverageJudgment(fact_index=2, covered=False, reason="no"),
        )
    )
    provider = make_provider(draft)

    covered = provider.judge("answer text", ["fact one", "fact two"])

    assert covered == (True, False)


def test_falls_back_to_normalized_index_when_a_fact_is_skipped():
    """If the model drops a fact, we can't zip by position -- fall back

    to index matching, still tolerant of a 0-based offset.
    """

    draft = FactCoverageDraft(
        judgments=(
            FactCoverageJudgment(fact_index=0, covered=True, reason="ok"),
            # fact_index 1 (fact two) is missing entirely.
            FactCoverageJudgment(fact_index=2, covered=True, reason="ok"),
        )
    )
    provider = make_provider(draft)

    covered = provider.judge(
        "answer text", ["fact one", "fact two", "fact three"]
    )

    assert covered == (True, False, True)


def test_no_facts_returns_empty_without_a_model_call():
    draft = FactCoverageDraft(judgments=())
    provider = make_provider(draft)

    covered = provider.judge("answer text", [])

    assert covered == ()
    assert provider.model.calls == []


def test_coverage_strips_trailing_sources_line_before_judging():
    """A trailing citation list must not reach the judge.

    Confirmed by direct A/B testing against the real local judge model:
    the exact same claim, same evidence, flips from covered to not-
    covered solely based on whether a "Sources: [S1] [S2]" line follows
    it -- the judge should only ever see the substantive answer.
    """

    provider = RecordingFactCoverageProvider(covered=(True,))
    judge = FactCoverageJudge(provider=provider)

    # The fact is a paraphrase, not a literal substring of the answer,
    # so it can't be resolved by the exact-match fast path -- this
    # exercises the LLM path, which is where the stripping matters.
    judge.coverage(
        "RAG-Sequence uses one document for the sequence. "
        "Sources: [S1] [S2]",
        (("the same passage is used for the whole sequence",),),
    )

    sent_answer, _ = provider.calls[0]
    assert "Sources:" not in sent_answer
    assert sent_answer == "RAG-Sequence uses one document for the sequence."


def test_coverage_collapses_whitespace_before_judging():
    provider = RecordingFactCoverageProvider(covered=(True, True))
    judge = FactCoverageJudge(provider=provider)

    judge.coverage(
        "First sentence.\nSecond   sentence.\n",
        (("fact one",), ("fact two",)),
    )

    sent_answer, _ = provider.calls[0]
    assert sent_answer == "First sentence. Second sentence."


def test_literal_match_skips_the_judge_entirely():
    """A bare keyword/name fact that appears verbatim needs no LLM call.

    Reproduces a real false negative found in production: the judge
    model, asked whether a one-word answer "conveys the meaning" of
    that same word, called it "no meaningful content" instead of
    recognizing the trivial exact match. Literal matching sidesteps the
    judge's own fragility on bare-keyword facts entirely.
    """

    provider = RecordingFactCoverageProvider(covered=())
    judge = FactCoverageJudge(provider=provider)

    coverage = judge.coverage(
        "Docling Sources: [S1]",
        (("Docling",),),
    )

    assert coverage.percent == 100.0
    assert coverage.missing_groups == ()
    assert provider.calls == []


def test_literal_match_only_applies_per_fact_not_per_answer():
    """One literal fact and one genuine paraphrase in the same answer:

    the literal one should never reach the judge, but the paraphrase
    still needs it. Reproduces a real false negative: "RAG-Token"
    named verbatim was still sent to (and rejected by) the judge
    alongside a genuinely-missing reasoning fact.
    """

    provider = RecordingFactCoverageProvider(covered=(False,))
    judge = FactCoverageJudge(provider=provider)

    coverage = judge.coverage(
        "RAG-Token performed better than RAG-Sequence. Sources: [S1]",
        (
            ("RAG-Token",),
            ("several documents", "multiple documents", "combine content"),
        ),
    )

    assert coverage.missing_groups == (
        ("several documents", "multiple documents", "combine content"),
    )
    # Only the non-literal fact should have gone to the judge.
    assert len(provider.calls) == 1
    _, facts_sent = provider.calls[0]
    assert facts_sent == (
        "several documents / multiple documents / combine content",
    )


def test_genuine_content_gap_is_still_flagged_after_literal_check():
    """A name that's simply absent must still be reported missing --

    the literal fast path isn't a way to paper over real gaps.
    """

    provider = RecordingFactCoverageProvider(covered=(False,))
    judge = FactCoverageJudge(provider=provider)

    coverage = judge.coverage(
        "Retrieval-augmented generation was introduced by Patrick Lewis "
        "and co-authors.",
        (("Patrick Lewis",), ("Ethan Perez",)),
    )

    assert coverage.percent == 50.0
    assert coverage.missing_groups == (("Ethan Perez",),)


def test_critical_facts_are_never_semantically_rescued():
    provider = RecordingFactCoverageProvider(
        covered=(True, True, True, True)
    )
    judge = FactCoverageJudge(provider=provider)
    groups = (
        ("$475.25",),
        ("September 30, 2026",),
        ("DARWIN-2048",),
        ("Patrick Lewis",),
        ("does not use the same document",),
    )

    result = judge.coverage("No critical values are present.", groups)

    assert result.percent == 0.0
    assert result.missing_groups == groups
    assert provider.calls == []


def test_close_process_paraphrase_is_covered_without_local_llm():
    provider = RecordingFactCoverageProvider(covered=())
    judge = FactCoverageJudge(provider=provider)

    result = judge.coverage(
        "RAG-Sequence generates the full output sequence for each "
        "single retrieved document before marginalizing.",
        (("one document per generated sequence",),),
    )

    assert result.percent == 100.0
    assert result.missing_groups == ()
    assert provider.calls == []


def test_unicode_dashes_and_compact_scale_values_are_exactly_covered():
    provider = RecordingFactCoverageProvider(covered=())
    judge = FactCoverageJudge(provider=provider)

    result = judge.coverage(
        "Articles were split into 100‑word chunks, yielding 21 M "
        "documents.",
        (
            ("100-word chunks", "100 word chunks"),
            ("21M", "21 million"),
        ),
    )

    assert result.percent == 100.0
    assert result.missing_groups == ()
    assert provider.calls == []


def test_noncritical_alternative_is_not_locked_by_negated_alternative():
    provider = RecordingFactCoverageProvider(covered=())
    judge = FactCoverageJudge(provider=provider)

    result = judge.coverage(
        "Add graph retrieval only after vector and lexical retrieval "
        "fail to retrieve the required relationships.",
        (("failures", "cannot reliably answer"),),
    )

    assert result.percent == 100.0
    assert result.missing_groups == ()
    assert provider.calls == []


def test_no_retraining_paraphrase_is_resolved_deterministically():
    provider = RecordingFactCoverageProvider(covered=(True,))
    judge = FactCoverageJudge(provider=provider)

    result = judge.coverage(
        "Hot-swapping updates knowledge at test time while avoiding "
        "any further training.",
        (
            (
                "without retraining",
                "without further training",
                "need further training",
            ),
        ),
    )

    assert result.percent == 100.0
    assert provider.calls == []

# DARWIN RAG Evaluation

This directory contains labeled regression datasets for measuring the RAG
pipeline. The default production suite is `production_cases.json`; it covers
PDFs, Markdown, OCR images, structured tables, cross-document questions,
conversation references, multi-part answers, and deliberate no-answer cases.

## What a case measures

- `expected_source_suffixes` identifies the evidence source retrieval should
  find. Multiple entries mean every listed source is required.
- `required_term_groups` lists required facts. Every inner group represents
  one fact, and any phrase inside that group is an accepted expression.
- `forbidden_terms` catches known incorrect or unsafe claims.
- `required_citation_source_suffixes` requires the final answer to cite every
  specified source, independently of citation precision.
- `expected_strategy` checks direct, decomposition, step-back, or conversation
  planning.
- `maximum_latency_seconds` is the per-case end-to-end latency budget.
- `tags` make it possible to run and compare one capability at a time.

## Commands

Run the local retrieval pipeline without spending generation tokens:

```bash
python -m app.ragv2.eval.evaluate --retrieval-only --progress
```

Run the full cloud-backed RAG benchmark and fail if a quality gate is missed:

```bash
python -m app.ragv2.eval.evaluate --enforce-gates
```

Run the full benchmark with local Qwen generation:

```bash
python -m app.ragv2.eval.evaluate --local-model --enforce-gates
```

Debug one case or one category without rerunning the full suite:

```bash
python -m app.ragv2.eval.evaluate \
  --case-id paper-attribution

python -m app.ragv2.eval.evaluate \
  --retrieval-only \
  --tag table
```

Save the complete machine-readable report:

```bash
python -m app.ragv2.eval.evaluate \
  --output data/ragv2/evaluation/latest-report.json
```

## Reading the report

- Retrieval quality: Hit@1, Hit@5, MRR, required-source recall, and query
  strategy accuracy.
- Answer quality: fact accuracy and completeness, grounded answer rate, and
  false-abstention rate.
- Citation quality: precision measures whether cited sources are acceptable;
  recall measures whether every required source was cited.
- Safety: no-answer rejection and false-answer rate.
- Performance: average, p95, per-case budgets, and retrieval-only latency.
- Reliability: execution success plus model calls grouped by provider and
  outcome, including rate limits, schema failures, and fallback usage.
- Diagnosis: per-tag category results show whether failures cluster around
  PDF reasoning, OCR, tables, conversations, or cross-document synthesis.

Quality gates belong in the dataset so a benchmark cannot be made to pass by
changing command-line thresholds after seeing the results. During debugging,
use case and tag filters; use the complete suite for release decisions.

# Core RAG v2 Benchmark Runbook

The release benchmark is split into four gates. Run them in order. A failed
gate stops the process so retrieval defects, provider limits, and generation
quality are never mixed into one misleading report.

## Gate 1: deterministic unit and integration tests

```bash
pytest -q
```

This validates the local code, contracts, parsers, indexes, retrieval stages,
generation workflow, safety rules, and evaluator without spending Groq quota.

## Gate 2: retrieval-only benchmark

```bash
python -m app.ragv2.eval.evaluate \
  --retrieval-only \
  --progress \
  --enforce-gates \
  --output data/ragv2/evaluation/retrieval_latest.json
```

This exercises query analysis, hybrid retrieval, reranking, evidence grading,
and context construction. It does not call the cloud answer generator.

## Gate 3: provider smoke test

```bash
python -m app.ragv2.eval.evaluate \
  --case-id invoice-amount \
  --progress \
  --output data/ragv2/evaluation/provider_smoke_latest.json
```

The command waits for a clean 60-second Groq window before running one bounded
case. Confirm that the report contains no provider failure, circuit-open event,
or Ollama fallback before starting the full benchmark.

## Gate 4: full end-to-end release benchmark

```bash
python -m app.ragv2.eval.evaluate \
  --progress \
  --enforce-gates \
  --output data/ragv2/evaluation/production_latest.json
```

The cloud benchmark automatically:

- waits 60 seconds before case one;
- runs at most two cases before each 60-second pause;
- stops immediately after a provider failure or fallback;
- writes skipped cases into the partial report;
- records the generated answer, citations, missing expected facts,
  verification reasoning, route history, and model-call errors.

The terminal shows readable summary, per-case, failure, and category tables.
Detailed JSON is saved to `--output` before a failing gate exits the process.
Add `--print-json` only when the raw machine-readable report is intentionally
needed in the terminal.

## Rerun only failed cases

After fixing a systemic issue, use the previous report to select its failed,
slow, skipped, or provider-contaminated cases:

```bash
python -m app.ragv2.eval.evaluate \
  --rerun-failed data/ragv2/evaluation/production_latest.json \
  --progress \
  --output data/ragv2/evaluation/failed_cases_latest.json
```

A focused rerun is diagnostic. Promotion still requires one uncontaminated
full run through all release cases.

## Emergency overrides

`--no-rate-pacing` disables scheduled waits. It does not disable fail-fast.
`--continue-on-provider-failure` disables fail-fast and therefore produces a
diagnostic run, not a valid release benchmark.

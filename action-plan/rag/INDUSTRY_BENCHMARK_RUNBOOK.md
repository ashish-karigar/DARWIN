# DARWIN industry benchmark runbook

This suite evaluates four different properties. They intentionally do not
share one score:

| Layer | What it measures | Uses an LLM judge? |
|---|---|---|
| RAGChecker | Claim-level retriever and generator diagnostics | Yes |
| RAGAS | Faithfulness, relevance, context precision, context recall | Yes |
| BEIR | Standard retrieval quality (nDCG, MAP, recall, precision, MRR) | No |
| Human calibration | Whether automated judges agree with careful review | Human |

All external data and indexes are isolated from Core RAG v2. Commands are
resumable. JSON is the lossless artifact; CSV and Markdown are the readable
reports.

## Environments

Use the normal `DARWIN` Conda environment for indexing and answering. Use the
isolated `.venv-industry-benchmarks` environment only for RAGChecker/RAGAS:

```bash
export PYTHONPATH=src
```

## 1. Confirm prepared public data

```bash
python - <<'PY'
from app.ragv2.eval.industry.config import settings
from app.ragv2.eval.industry.datasets import discover_datasets, load_cases

for name in discover_datasets(settings.processed_root):
    print(name, len(load_cases(settings.processed_root, name)))
PY
```

RAGChecker domains are BioASQ, CLAPNQ, FiQA, KIWI, NovelQA, and the five
LoTTE domains. Representative BEIR datasets are SciFact, NFCorpus, FiQA, and
ArguAna.

## 2. Run DARWIN over one RAGChecker domain

The first invocation builds a fingerprinted local index. Later invocations
resume both indexing and question execution. The runner stops before DARWIN's
10,000-token daily reserve.

```bash
python -m app.ragv2.eval.industry.runner novelqa --limit 10 --progress
```

Repeat without changing the command until all cases are complete, then do the
same for each domain. Artifacts are written under
`data/ragv2/industry_benchmarks/runs/<domain>/`.

## 3. Score a bounded shard with RAGChecker

Groq is the primary judge. The conservative 8,000-token estimate prevents a
shard that would exceed the tracked 200,000-token daily budget. Increase the
offset on later runs.

```bash
.venv-industry-benchmarks/bin/python \
  -m app.ragv2.eval.industry.scoring ragchecker \
  data/ragv2/industry_benchmarks/runs/novelqa/ragchecker_input.json \
  data/ragv2/industry_benchmarks/reports/ragchecker/novelqa_groq_000.json \
  --judge groq \
  --offset 0 \
  --limit 20
```

Use Ollama on the selected 50-case calibration packet, not as a replacement
for the primary judge:

```bash
.venv-industry-benchmarks/bin/python \
  -m app.ragv2.eval.industry.scoring ragchecker \
  data/ragv2/industry_benchmarks/reports/human_calibration/ragchecker_input.json \
  data/ragv2/industry_benchmarks/reports/ragchecker/calibration_ollama.json \
  --judge ollama
```

## 4. Score the same shard with RAGAS

RAGAS produces faithfulness, response relevance, context precision, and
context recall. Its default Groq estimate is 6,000 tokens per case.

```bash
.venv-industry-benchmarks/bin/python \
  -m app.ragv2.eval.industry.scoring ragas \
  data/ragv2/industry_benchmarks/runs/novelqa/ragas_input.jsonl \
  data/ragv2/industry_benchmarks/reports/ragas/novelqa_groq_000.json \
  --judge groq \
  --offset 0 \
  --limit 20
```

## 5. Run BEIR retrieval benchmarks

These runs are local and spend no Groq tokens:

```bash
python -m app.ragv2.eval.industry.beir run scifact --progress
python -m app.ragv2.eval.industry.beir run nfcorpus --progress
python -m app.ragv2.eval.industry.beir run fiqa --progress
python -m app.ragv2.eval.industry.beir run arguana --progress
```

Each query is checkpointed under `runs/beir_<dataset>/retrieval.jsonl`.

## 6. Generate the 50-case human review packet

After at least 50 RAGChecker samples have completed:

```bash
python -m app.ragv2.eval.industry.calibration --size 50
```

Review `human_review_50.md` or fill the scoring columns in
`human_review_50.csv`. The JSON file preserves the complete machine-readable
sample.

## 7. Compare Groq and Ollama judges

After both judges score the same 50 records:

```bash
.venv-industry-benchmarks/bin/python \
  -m app.ragv2.eval.industry.scoring agreement \
  path/to/calibration_groq.json \
  path/to/calibration_ollama.json \
  data/ragv2/industry_benchmarks/reports/judge_agreement.json
```

Treat disagreement as a calibration finding, not as proof that either judge
is correct. The human-reviewed table is the tie-breaker.

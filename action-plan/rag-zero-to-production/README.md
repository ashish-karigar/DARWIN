# DARWIN RAG: Zero to Production

## Purpose

This is the implementation syllabus for turning DARWIN's current two-file RAG demo into a measurable document intelligence system. It is designed for learning as well as delivery: each module explains the production concept, implements it in the existing Python project, and ends with a testable gate.

The target system will:

- ingest hundreds or thousands of web pages and local documents;
- resume safely after interruption without duplicating vectors;
- preserve source, version, access, and citation metadata;
- retrieve across heterogeneous documents with measurable quality;
- answer only from sufficient evidence and abstain otherwise;
- expose latency, freshness, queue, retrieval, and answer-quality diagnostics;
- remain local-first while allowing Groq for reasoning where configured.

## What the current score proves—and does not prove

Current baseline:

| Measure | Result |
| --- | ---: |
| Evaluation cases | 16 |
| Retrieval accuracy | 100% |
| Hit@1 | 90.9% |
| Hit@3 | 100% |
| No-answer rejection | 100% |
| MRR | 0.969 |
| Mean retrieval latency | 0.058 s |
| Required-term answer accuracy | 100% |

This proves that the present pipeline works for a tiny, known corpus. It does not establish robustness across formats, semantic ambiguity, conflicting facts, changing web content, multi-hop questions, access boundaries, prompt injection, or production load. Re-running these same 16 cases is regression testing, not further learning.

## System boundary

Keep two different workflows separate.

### Offline data plane: deterministic ingestion

```text
Source registry
    -> durable job queue
    -> fetch and snapshot
    -> parse and normalize
    -> classify and enrich metadata
    -> structure-aware chunking
    -> embed in batches
    -> lexical + vector indexes
    -> validation
    -> publish index version
```

Ingestion is ETL, not an agent. An LLM may optionally enrich metadata, but it must never decide whether a document was successfully stored.

### Online query plane: bounded LangGraph workflow

```text
Question
    -> classify intent and source scope
    -> analyze/rewrite query only if needed
    -> retrieve dense + lexical candidates
    -> fuse, deduplicate, and rerank
    -> assemble evidence within token budget
    -> grade evidence sufficiency
       -> sufficient: generate grounded answer
       -> weak: one bounded retrieval retry
       -> insufficient: abstain or use an explicit live-data tool
    -> verify claims and citations
    -> answer
```

LangGraph owns this online state machine because it benefits from typed state, conditional routing, persistence, and traces. Retrieval, parsing, ranking, and validation remain ordinary deterministic Python services.

## Proposed project structure

```text
src/app/rag/
├── config.py                   # Typed settings and version identifiers
├── contracts.py                # Document, Chunk, Evidence, Answer schemas
├── registry.py                 # Source definitions and access scopes
├── catalog.py                  # Source/version/job ledger
├── pipeline/
│   ├── discover.py             # Resolve files, feeds, URLs, sitemaps
│   ├── fetch.py                # Download with retries and cache validators
│   ├── parse.py                # Parser selection and normalization
│   ├── enrich.py               # Metadata and optional LLM enrichment
│   ├── chunk.py                # Structure-aware parent/child chunking
│   ├── embed.py                # Batching and embedding cache
│   ├── index.py                # Idempotent index writes/deletes
│   └── validate.py             # Count/hash/search smoke checks
├── parsers/
│   ├── text.py
│   ├── web.py
│   ├── pdf.py
│   └── office.py
├── queue/
│   ├── models.py
│   ├── repository.py
│   └── worker.py
├── stores/
│   ├── vector.py               # VectorIndex protocol
│   ├── chroma.py               # Chroma implementation
│   ├── lexical.py              # BM25/FTS implementation
│   └── records.py              # Durable ingestion record manager
├── retrieval/
│   ├── analyze.py
│   ├── dense.py
│   ├── sparse.py
│   ├── fusion.py
│   ├── rerank.py
│   ├── context.py
│   └── service.py
├── graph/
│   ├── state.py
│   ├── nodes.py
│   ├── policies.py
│   └── workflow.py
├── evaluation/
│   ├── datasets.py
│   ├── retrieval.py
│   ├── generation.py
│   ├── routing.py
│   ├── security.py
│   └── report.py
└── observability/
    ├── events.py
    ├── metrics.py
    └── diagnostics.py

data/rag/
├── raw/                        # Immutable source snapshots
├── parsed/                     # Normalized structured documents
├── manifests/                  # Build inputs, hashes, and versions
├── evaluation/                 # Labeled train/dev/holdout cases
└── reports/                    # Timestamped benchmark results
```

This is the destination structure. Add it module by module; do not generate empty scaffolding all at once.

## Core contracts

Every stored chunk must carry enough information to reproduce, filter, delete, and cite it:

```text
Document
- source_id: stable logical identifier
- source_uri: original file path or URL
- source_type: web, pdf, docx, markdown, text, code
- title, authors, published_at, fetched_at
- content_hash and source_version
- access_scope and trust_tier
- parser_name and parser_version
- raw_snapshot_path

Chunk
- chunk_id: deterministic hash
- source_id and source_version
- parent_id
- text
- heading_path, page, section, offsets
- chunk_strategy and chunk_version
- embedding_model and embedding_version
- token_count

Evidence
- chunk_id, source_id, source_uri
- exact supporting text
- dense_score, lexical_score, fused_rank, reranker_score
- citation label and metadata
```

Stable IDs are essential. A chunk ID should be derived from the logical source, source version, normalized content, and chunking version—not from insertion order.

## Multi-document ingestion and queue design

### Durable states

```text
DISCOVERED -> QUEUED -> FETCHING -> PARSED -> CHUNKED
           -> EMBEDDING -> INDEXED -> VALIDATING -> READY

Any active state -> RETRY_WAIT -> previous stage
Exceeded retry policy -> DEAD_LETTER
```

The queue record stores attempts, next retry time, last error, worker lease, source version, pipeline version, and timestamps. A crashed worker's lease expires so another worker can resume it.

### Idempotency

Use this logical key:

```text
SHA256(source_id + source_version + pipeline_version)
```

- The same job submitted twice produces one active job.
- The same unchanged source is skipped.
- A changed source creates a new version and atomically replaces its old chunks only after validation.
- Failed partial writes can safely retry.
- Deletes are scoped by `source_id` and index version.

### Local and scaled execution

For the laptop version:

- SQLite is the durable job/catalog database.
- A small fetch/parse worker pool handles I/O-bound work.
- Embeddings are submitted in bounded batches.
- One vector-writer process avoids Chroma write contention.
- Backpressure pauses discovery when the embedding or write queue is full.

For a service deployment, preserve the same queue interface and replace the implementation with Postgres plus Celery using Redis or RabbitMQ. Celery tasks must remain idempotent, use bounded retries with exponential backoff and jitter, and acknowledge only after successful completion.

### Source lifecycle

1. Discover the source.
2. Compare ETag, Last-Modified, size, and content hash with the catalog.
3. Snapshot the raw content before parsing.
4. Parse and validate non-empty structured output.
5. Build a candidate index version.
6. Run retrieval smoke tests and count/hash checks.
7. Publish the candidate atomically.
8. Retain the previous version for rollback.

## Parsing heterogeneous sources

Recommended order:

- Markdown, plain text, and code: native parsers that retain headings and offsets.
- Web pages: Trafilatura to remove navigation, ads, and boilerplate; keep URL and fetch metadata.
- PDF and Office formats: Docling to retain layout, headings, tables, pages, and reading order.
- Scanned documents: OCR path with an explicit OCR confidence field.

Never flatten everything immediately into one string. Preserve structure first, then derive chunks. Store parser warnings, extracted character count, page count, and table count so bad documents are visible.

Web ingestion must respect the site's terms, robots policy, rate limits, copyright, and data sensitivity. Public availability is not equivalent to unrestricted reuse.

## Chunking strategy

There is no universally correct chunk size. Evaluate strategies per document class:

| Content | Initial strategy |
| --- | --- |
| Prose/docs | heading-aware child chunks of 256/384/512 tokens |
| Long sections | parent chunks of 1,024/1,536 tokens linked to children |
| Tables | table plus title/header context; never arbitrary row splits |
| Code | symbol/AST boundaries with file and symbol metadata |
| FAQs | question-answer pair as a unit |

Start with 10–15% overlap only where sentence/section boundaries cannot preserve continuity. Excess overlap increases storage, duplicate retrieval, context waste, and false confidence.

Run a controlled matrix over chunk size, overlap, parent expansion, and top-k. Select using holdout nDCG/recall plus latency—not intuition.

## Embeddings and index versioning

- Keep `nomic-embed-text` as the first baseline; benchmark before replacing it.
- Cache embeddings by `SHA256(normalized_text + model_id + model_revision)`.
- Store vector dimension and normalization settings in the build manifest.
- Never mix embedding models or revisions in one index version.
- Build a new collection/index for a model migration, evaluate it, then switch an alias/config pointer.
- Retain the prior index for rollback.

Chroma remains behind a `VectorIndex` protocol. Develop locally with persistent Chroma and move to client-server mode when concurrent processes need one shared service. Chroma Cloud offers native hybrid Search API features; for local/self-hosted Chroma, implement lexical retrieval and rank fusion in DARWIN so the behavior stays portable.

The ingestion ledger—not Chroma—is the source of truth. LangChain's record manager and the vector store are separate systems, so DARWIN must detect and repair divergence.

## Retrieval architecture

### Candidate pipeline

1. Apply tenant, access, source-type, time, and document filters.
2. Dense retrieval: top 30.
3. Lexical/BM25 retrieval: top 30.
4. Reciprocal Rank Fusion (RRF).
5. Deduplicate near-identical chunks and enforce source diversity.
6. Local cross-encoder rerank: top 20 candidates.
7. Select top 5–8 evidence chunks.
8. Expand to linked parents only where extra context is needed.
9. Pack evidence under a measured token budget.

Dense retrieval handles semantic similarity; lexical retrieval protects exact names, identifiers, numbers, and code. A cross-encoder is slower but more precise, so it is applied only to the small fused candidate set. Begin with a compact local MS MARCO cross-encoder and benchmark its latency on the M3 Pro.

### Query analysis

The fast path retrieves the original query directly. Invoke the reasoning model only when the query needs:

- conversational reference resolution;
- decomposition into multiple facts;
- metadata filters;
- acronym/entity normalization;
- a second retrieval attempt after insufficient evidence.

Limit rewriting to one retry. Unlimited agentic search increases cost, latency, and nondeterminism.

### Retrieval maintenance

- Re-evaluate on every corpus, chunker, embedding, ranking, or threshold change.
- Track zero-result, low-score, disagreement, and user-correction queries.
- Convert reviewed failures into new evaluation cases.
- Watch score distributions and retrieval drift, not only averages.
- Rebuild stale indexes when parser/embedding/chunker versions change.
- Run scheduled consistency checks between catalog rows and indexed chunk IDs.

## Grounding and hallucination controls

The generator receives a typed evidence bundle, not arbitrary concatenated text. Retrieved content is untrusted data and is clearly delimited from system instructions.

Required policies:

- answer factual corpus questions only from retrieved evidence;
- cite each externally verifiable claim;
- validate that citations refer to evidence actually supplied;
- state conflicts instead of silently choosing one source;
- prefer newer or authoritative sources only through explicit metadata policy;
- abstain when evidence is absent, weak, or contradictory;
- route live facts such as weather to live tools, not the document index;
- never follow instructions embedded in retrieved documents;
- filter by access scope before retrieval, not after generation.

After generation, a verifier maps claims to citations. Unsupported claims cause one correction pass; if still unsupported, return an evidence-limited answer or abstention.

## LangGraph workflow

Use typed state similar to:

```text
RagState
- question and conversation context
- intent and source filters
- retrieval_queries
- candidates and reranked_evidence
- evidence_sufficient and insufficiency_reason
- retrieval_attempts
- draft_answer
- claim_citation_checks
- final_answer
- timing and trace identifiers
```

Nodes should be narrow and testable:

1. `classify_request`
2. `analyze_query`
3. `retrieve_candidates`
4. `fuse_and_rerank`
5. `assemble_context`
6. `grade_evidence`
7. `rewrite_once` when justified
8. `generate_answer`
9. `verify_grounding`
10. `correct_or_abstain`

Persist checkpoints for recoverability, but keep corpus ingestion out of graph state. SQLite is appropriate locally; use a production database-backed checkpointer for a deployed multi-user service.

## Evaluation program

### Retrieval metrics

- Recall/Hit@1, @3, @5, @10
- Precision@k
- Mean Reciprocal Rank (MRR)
- nDCG@10
- context precision and context recall
- no-answer precision, recall, and F1
- p50/p95/p99 retrieval latency

### Answer metrics

- exact match/token F1 where a canonical answer exists
- required-fact completeness
- semantic correctness
- faithfulness to supplied context
- citation precision and citation recall
- unsupported-claim rate
- contradiction handling
- appropriate abstention rate

Use deterministic checks first. LLM-as-judge can supplement them, but judge prompts, model, temperature, and evidence must be versioned. A human-reviewed holdout set remains the authority.

### Agent/workflow metrics

- correct decision to retrieve or use a live tool
- correct source scope and filters
- rewrite/decomposition usefulness
- graph trajectory correctness
- retry and fallback rate
- answer and failure latency by node

### Ingestion and operations metrics

- documents discovered, ready, skipped, failed, and dead-lettered
- chunks and tokens per source
- documents/minute and embeddings/second
- queue depth and oldest-job age
- embedding-cache hit rate
- corpus freshness lag
- catalog/index consistency
- error counts by stage/parser/source

### Security tests

- prompt injection inside retrieved documents
- poisoned or misleading documents
- unauthorized-scope retrieval
- malicious HTML/PDF content
- denial-of-service documents and oversized inputs
- secrets or personal data in logs and evidence

## Real-world benchmark

### Corpus v1: AI engineering knowledge base

Build a reproducible snapshot from authoritative public sources:

- LangChain and LangGraph documentation;
- Chroma documentation;
- Groq and Ollama documentation;
- Ragas and Sentence Transformers documentation;
- OWASP LLM security guidance;
- selected primary research papers such as RAG, BEIR, MTEB, Natural Questions, and HotpotQA.

Start with 50–100 pages spanning HTML, Markdown, and PDF; then scale the same pipeline to 500+ documents. Save the raw response, canonical URL, fetch time, content hash, ETag/Last-Modified where present, parser version, and license/usage note.

### Question set

Create 100 human-reviewed questions:

| Category | Count |
| --- | ---: |
| Single-source factual | 25 |
| Exact configuration/API/version details | 20 |
| Cross-document comparison/synthesis | 20 |
| Multi-hop reasoning | 10 |
| Conflicting or freshness-sensitive facts | 10 |
| Unanswerable from the corpus | 10 |
| Prompt-injection/poisoning resistance | 5 |

For every question label:

- canonical answer or abstention;
- required and forbidden claims;
- relevant document and chunk IDs;
- acceptable alternate evidence;
- expected source/tool route;
- freshness date;
- difficulty and category.

Keep 20% hidden as a holdout set. Development results may tune the system; holdout results decide promotion. Add small public benchmark slices from BEIR/MTEB for retrieval and Natural Questions/HotpotQA for QA sanity checks, but do not treat their scores as a substitute for DARWIN's own use-case evaluation.

## Initial promotion gates

These are engineering targets, not universal claims:

| Area | Gate |
| --- | --- |
| Idempotency | Re-ingesting unchanged corpus creates zero duplicate chunks |
| Updates | Changing one source replaces only that source's active version |
| Recovery | Forced interruption resumes without loss or duplication |
| Retrieval | Recall@10 ≥ 90%, MRR ≥ 0.80, nDCG@10 ≥ 0.80 |
| No answer | Unanswerable F1 ≥ 0.90 |
| Answers | Human-reviewed correctness ≥ 85% |
| Grounding | Faithfulness ≥ 95%; unsupported claims ≤ 2% |
| Citations | Precision ≥ 95%; recall ≥ 90% |
| Latency | Warm retrieval p95 < 800 ms on the target Mac |
| Security | Zero cross-scope leaks and zero successful known injection overrides |

Record hardware, corpus size, cold/warm state, model versions, and concurrency alongside every latency result.

## Syllabus and delivery sequence

### Module 0 — Reproducible baseline

Learn: why a metric without a build identity is not reproducible.

Build:

- `RagBuildManifest` containing source hashes, corpus/index version, parser/chunker/embedding/reranker versions, evaluation-set hash, Git commit, and settings;
- manifest ID embedded into every evaluation and diagnostic report;
- stale-index detection in diagnostics.

Gate: the same inputs create the same manifest ID; changing any relevant input marks old reports stale.

### Module 1 — Contracts and source registry

Learn: provenance, stable IDs, metadata filtering, trust, and access scope.

Build typed `Document`, `Chunk`, `Evidence`, and `Answer` contracts plus a declarative source registry.

Gate: schema tests reject missing provenance, invalid scopes, and non-deterministic IDs.

### Module 2 — Durable catalog and ingestion queue

Learn: idempotency, leases, retries, dead letters, and backpressure.

Build SQLite catalog/job repositories and a resumable worker CLI.

Gate: ingest 100 mixed jobs, kill the worker mid-run, restart, and finish with one READY version per source and no duplicate chunks.

### Module 3 — Production parsers

Learn: extraction quality is a retrieval dependency.

Build web, PDF/Office, Markdown/text, and failure/quarantine paths. Preserve raw snapshots.

Gate: a golden parsing set validates headings, tables, URLs/pages, text coverage, and corrupted-file behavior.

### Module 4 — Chunking, embeddings, and versioned indexes

Learn: parent/child retrieval, tokenization, batching, caching, migrations.

Build strategy-aware chunkers, embedding cache, candidate index builds, validation, atomic publish, and rollback.

Gate: unchanged rebuild is mostly cache hits; a model/chunker change creates a separate comparable index.

### Module 5 — Retrieval laboratory

Learn: dense vs lexical retrieval, RRF, reranking, filters, and context packing.

Build the staged retriever and an experiment runner for chunk/top-k/fusion/reranker settings.

Gate: select a configuration from holdout-independent evidence showing quality/latency tradeoffs and ablations.

### Module 6 — Grounded answer and citation layer

Learn: evidence sufficiency, faithful synthesis, citations, abstention, conflicts.

Build structured generation, claim-to-citation verification, one correction pass, and explicit abstention.

Gate: meet answer, grounding, citation, and no-answer thresholds on the development set.

### Module 7 — LangGraph production workflow

Learn: typed state, conditional routing, bounded loops, checkpoints, and traces.

Build the online graph around the deterministic retrieval service and add live-tool routing.

Gate: routing/trajectory tests pass and every query produces a trace explaining retrieval, retry, tool, or abstention decisions.

### Module 8 — Real-world corpus and evaluation

Learn: dataset design, leakage control, hard negatives, human review, and judge calibration.

Build corpus v1, 100 labeled questions, 20% holdout, Ragas-supported metrics, and a failure-analysis report.

Gate: meet promotion targets on the untouched holdout and manually audit every unsupported claim or false answer.

### Module 9 — Performance and operations

Learn: p95/p99, capacity, freshness, queue health, and observability.

Build structured events, diagnostics, load tests, cache/batch tuning, and queue dashboards/reports.

Gate: ingest and query load remain within measured latency/error budgets, and diagnostics detect deliberately injected failures.

### Module 10 — Release, rollback, and continuous improvement

Learn: safe corpus/index promotion and regression prevention.

Build candidate/shadow evaluation, version promotion, rollback, data retention, and failure-to-test workflow.

Gate: promote and roll back an index without downtime; each reviewed production failure becomes a permanent regression case.

## Recommended immediate work

Start with Module 0 only. Do not ingest a larger corpus until the current build can prove exactly which sources, settings, models, code, and evaluation set produced a score. Otherwise every later comparison is ambiguous.

The first implementation should add:

1. `src/app/rag/manifest.py` with a typed immutable manifest.
2. A manifest writer invoked after successful ingestion.
3. `manifest_id` and `index_version` in evaluation output.
4. A diagnostic check that reports missing or stale manifests.
5. Unit tests proving deterministic hashes and stale detection.

## Decision log

- Keep Python, LangChain interfaces, LangGraph orchestration, Groq reasoning, Ollama/local embeddings, and Chroma for the first production iteration.
- Do not change vector databases until a measured workload shows Chroma is the bottleneck.
- Treat the catalog/ledger as authoritative and vector/lexical indexes as rebuildable derivatives.
- Use deterministic retrieval before agentic retries.
- Allow at most one query rewrite/retrieval retry.
- Keep the voice stack out of RAG evaluation so speech errors do not contaminate retrieval metrics.
- Treat retrieved documents as untrusted input.
- Require human-reviewed holdout results before calling the system production-ready.

## Research sources

- [LangGraph overview and durable execution](https://docs.langchain.com/oss/python/langgraph/overview)
- [LangGraph persistence and checkpointers](https://docs.langchain.com/oss/python/langgraph/persistence)
- [LangGraph agentic RAG workflow](https://docs.langchain.com/oss/python/langgraph/agentic-rag)
- [LangChain custom workflows and typed state](https://docs.langchain.com/oss/python/langchain/multi-agent/custom-workflow)
- [LangChain indexing API](https://reference.langchain.com/python/langchain-core/indexing/api/aindex)
- [LangChain RecordManager consistency caveat](https://reference.langchain.com/python/langchain-core/indexing/base/RecordManager)
- [LangChain document loaders and lazy loading](https://docs.langchain.com/oss/python/integrations/document_loaders/index)
- [Docling supported document formats](https://docling-project.github.io/docling/usage/supported_formats/)
- [Trafilatura web extraction](https://trafilatura.readthedocs.io/en/latest/)
- [Robots Exclusion Protocol, RFC 9309](https://www.rfc-editor.org/rfc/rfc9309.html)
- [Celery task idempotency, acknowledgements, and retries](https://docs.celeryq.dev/en/stable/userguide/tasks.html)
- [Chroma client-server deployment](https://docs.trychroma.com/guides/deploy/client-server-mode)
- [Chroma performance guidance](https://docs.trychroma.com/production/administration/performance)
- [Chroma querying and metadata filters](https://docs.trychroma.com/docs/querying-collections/query-and-get)
- [Chroma Cloud Search API](https://docs.trychroma.com/cloud/search-api/overview)
- [Chroma Cloud hybrid search and RRF](https://docs.trychroma.com/cloud/search-api/hybrid-search)
- [Sentence Transformers retrieve-and-rerank](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)
- [Ragas metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/)
- [Ragas faithfulness](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/faithfulness/)
- [OWASP prompt injection risk](https://genai.owasp.org/llmrisk/llm01-prompt-injection/)
- [OWASP vector and embedding weaknesses](https://genai.owasp.org/llmrisk/llm082025-vector-and-embedding-weaknesses/)
- [Original Retrieval-Augmented Generation paper](https://arxiv.org/abs/2005.11401)
- [BEIR heterogeneous retrieval benchmark](https://arxiv.org/abs/2104.08663)
- [MTEB benchmark](https://arxiv.org/abs/2210.07316)
- [Natural Questions benchmark](https://research.google/pubs/natural-questions-a-benchmark-for-question-answering-research/)
- [HotpotQA multi-hop benchmark](https://hotpotqa.github.io/)

## Definition of done

DARWIN's RAG is production-level for its declared workload only when it can reproducibly ingest and update a heterogeneous corpus, recover from failures, enforce source scopes, meet holdout retrieval and grounded-answer targets, resist the tested injection/poisoning cases, explain each answer with valid evidence, stay within measured latency budgets, and roll back safely.

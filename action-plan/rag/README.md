# DARWIN Advanced RAG Build Plan

## Objective

Build DARWIN's current basic RAG into an advanced, grounded RAG system that can:

- understand several document formats;
- preserve document structure and source information;
- index multiple representations of the same information;
- understand, rewrite, and decompose complex questions;
- combine multiple retrieval methods;
- judge whether retrieved evidence is useful;
- perform corrective retrieval or an approved web search;
- generate answers with document, page, and URL citations;
- verify its answer and retry once when necessary.

This plan focuses on the **document intelligence, retrieval, and grounded-generation core**. The operational work intentionally deferred by the project owner is listed under [Future production hardening](#future-production-hardening).

> Important: the result of this plan will be a production-quality RAG core, but it should not be described as fully production-ready until the deferred reliability, security, evaluation, and operations work is completed.

## Target architecture

```text
Documents and websites
        │
        ▼
Parser router
 ├─ Native text/Markdown parser
 ├─ Trafilatura web parser
 ├─ Docling PDF/Office parser
 └─ LLM/vision-assisted parser for difficult pages
        │
        ▼
Normalized document model
        │
        ▼
Structure-aware chunking
        │
        ├─ child text chunks ────────► vector index
        ├─ keywords/entities ────────► lexical index
        ├─ parent sections ──────────► document store
        ├─ tables/structured data ───► structured store
        └─ relationships ────────────► optional graph index

User question
        │
        ▼
Question analyzer
 ├─ direct query
 ├─ conversation resolution
 ├─ decomposition
 └─ step-back query
        │
        ▼
Hybrid retrieval
        │
        ▼
Fusion → deduplication → reranking → relevance grading
        │
        ├─ sufficient evidence ──────► generation
        ├─ weak evidence ────────────► rewrite and retrieve once
        └─ missing evidence ─────────► approved web search or abstain
                                             │
                                             ▼
                              grounded answer with citations
                                             │
                                             ▼
                                  claim/evidence verification
```

## Design principles

1. **Use deterministic code for predictable work.** File detection, parsing selection, metadata validation, chunk creation, filtering, and citation assembly should not depend on an LLM.
2. **Use an LLM only where reasoning adds value.** Difficult document reconstruction, query decomposition, relevance grading, synthesis, and claim verification are suitable uses.
3. **Keep the simple path fast.** A direct factual question should not pass through decomposition, graph traversal, or web search unnecessarily.
4. **Preserve provenance from the beginning.** Every chunk must retain its document, page, section, and URL information.
5. **Retrieved documents are evidence, not instructions.** Text inside a document must never control DARWIN's workflow.
6. **No evidence means no factual claim.** DARWIN should abstain or clearly identify an ungrounded general response.
7. **Graph retrieval is optional.** Add it only when the corpus contains relationships that vector and lexical search cannot reliably answer.

## 1. Document parsing

### Parser router

Select the cheapest parser that preserves the required information:

| Input | Primary parser | Escalation path |
| --- | --- | --- |
| Plain text | Native Python | None |
| Markdown | Markdown-aware parser | None |
| HTML/web page | Trafilatura | Docling or targeted browser extraction |
| PDF | Docling | LLM/vision-assisted parsing for failed pages |
| DOCX/PPTX/XLSX | Docling | LLM/vision assistance for complex visual content |
| Scanned document/image | Docling with OCR | Vision model when OCR confidence is poor |
| Source code | Language/symbol-aware parser | Plain-text fallback |

Do not send every document through an LLM. Clean text should remain deterministic, local, inexpensive, and fast.

### LLM-assisted parsing

Use LLM or vision assistance only when the normal parser detects:

- broken reading order;
- complex or cross-page tables;
- charts whose meaning is not present in surrounding text;
- handwriting;
- low OCR confidence;
- missing section hierarchy;
- formulas that were extracted incorrectly.

The assisted parser must return the same normalized schema as every other parser. Its output is still validated before indexing.

### Normalized document contract

```python
Document:
    document_id
    title
    source_type
    source_path_or_url
    authors
    published_at
    parsed_at
    sections[]
    tables[]
    images[]
    metadata

Section:
    section_id
    heading_path
    text
    page_number
    start_offset
    end_offset
```

## 2. Structure-aware chunking

Chunk according to meaning rather than blindly cutting every fixed number of characters.

### Parent-child model

- **Child chunks** are small and precise, making them easier to retrieve.
- **Parent sections** provide the surrounding explanation needed to answer correctly.
- Search child chunks, then return the associated parent text when necessary.

Initial experiments:

- prose children: 256, 384, or 512 tokens;
- parent sections: approximately 1,024–1,536 tokens;
- overlap: 10–15% only when natural boundaries are unavailable;
- tables: keep headers, captions, units, and related rows together;
- code: split by file, class, function, or symbol;
- FAQs: preserve each question-answer pair as one unit.

### Chunk contract

```python
Chunk:
    chunk_id
    document_id
    parent_id
    text
    heading_path
    page_number
    source_url
    content_type
    token_count
    entities[]
    keywords[]
```

## 3. Multi-representation indexing

One document can have several searchable representations:

### Dense semantic representation

Store text embeddings in Chroma. This finds conceptually similar information even when the wording differs.

### Lexical representation

Store searchable terms in a BM25 or full-text index. This protects exact matches such as:

- names;
- model numbers;
- error codes;
- dates;
- identifiers;
- uncommon technical phrases.

### Parent-document representation

Keep complete parent sections outside the vector index. A retrieved child points back to the larger section so DARWIN can recover context without embedding huge passages.

### Structured representation

Store clean tables or extracted fields in a structured form when questions require exact aggregation, comparison, or filtering. Do not rely only on embeddings to perform arithmetic over tables.

### Graph representation—only when justified

Use a graph when the corpus requires explicit multi-hop relationships, for example:

```text
person → works_for → company
company → owns → product
product → depends_on → component
```

A graph database is not automatically required for advanced RAG. Begin with vector, lexical, parent, and structured representations. Add a graph after demonstrating relationship-based retrieval failures.

## 4. Question understanding

The question analyzer chooses one of four paths.

### Direct retrieval

Use the original question when it is already clear and contains one information need.

### Conversation resolution

Convert references such as “What about its price?” into a standalone question using the relevant conversation context.

### Decomposition

Split a compound question into independent searchable questions.

```text
Who created DARWIN and which retrieval database does it use?

1. Who created DARWIN?
2. Which retrieval database does DARWIN use?
```

Retrieve evidence for each subquestion, then synthesize the combined answer.

### Step-back prompting

Generate a broader question when background knowledge is necessary to answer a narrow question.

```text
Original: Why does DARWIN combine dense and keyword retrieval?
Step back: What are the strengths and weaknesses of dense and keyword retrieval?
```

Use decomposition and step-back only when the classifier says they are helpful. Applying them to every question wastes time and may change the user's intent.

## 5. Hybrid retrieval

### Retrieval flow

```text
original/subquery
    ├─ dense vector search
    ├─ lexical keyword search
    ├─ optional structured query
    └─ optional graph traversal
            │
            ▼
rank fusion
    → duplicate removal
    → source diversity
    → cross-encoder reranking
    → top evidence
```

Recommended first implementation:

1. Retrieve the top 20–30 dense candidates.
2. Retrieve the top 20–30 lexical candidates.
3. Combine their ranks using Reciprocal Rank Fusion.
4. Remove duplicate or nearly identical chunks.
5. Rerank the best 15–20 candidates with a local cross-encoder.
6. Select approximately 5–8 evidence chunks.
7. Expand selected chunks to their parents only when required.

The LLM should not manually inspect every document. Retrieval narrows the corpus first; relevance grading examines only the small candidate set.

## 6. Corrective RAG

After reranking, grade the evidence as one of:

```text
SUFFICIENT
PARTIAL
IRRELEVANT
```

### Sufficient

Proceed to grounded generation.

### Partial

Identify the missing fact, rewrite only that query, and retrieve one additional time.

### Irrelevant

If web search is permitted for the request, perform a targeted search and grade those results. Otherwise abstain.

### Critical rule

If document retrieval and web search both fail, DARWIN must not fabricate a sourced answer from model memory. It should say that reliable evidence was not found. A general model-knowledge answer may be offered only when clearly labelled as unverified and the user requests it.

## 7. Grounded generation and citations

The generation model receives:

```text
- the resolved user question;
- the evidence bundle;
- source labels;
- instructions to use only that evidence for factual claims;
- an explicit output schema.
```

Suggested answer contract:

```python
GroundedAnswer:
    answer
    citations[]
    answered_subquestions[]
    unanswered_subquestions[]
    confidence_reason
```

Each citation should preserve:

- document title or filename;
- page number when available;
- section heading;
- website URL when applicable;
- chunk/evidence identifier internally.

The user-facing response can remain conversational while the structured citation data stays available to the application.

## 8. Active retrieval and answer verification

After drafting an answer:

1. Extract its factual claims.
2. Map every claim to supporting evidence.
3. Detect missing, contradicted, or weakly supported claims.
4. Retrieve again only for a specific missing claim.
5. Regenerate or correct the answer once.
6. Remove unsupported claims or abstain if evidence remains insufficient.

The workflow must be bounded. One corrective retrieval and one correction pass are enough for the first version.

## 9. LangGraph workflow

LangGraph coordinates the online reasoning flow. Parsing and indexing remain separate services.

```text
START
  → classify_question
  → resolve_and_plan_query
  → retrieve_candidates
  → fuse_and_rerank
  → grade_evidence
      ├─ sufficient → generate
      ├─ partial → rewrite_missing_fact → retrieve_candidates
      └─ irrelevant → web_search_or_abstain
  → verify_claims
      ├─ supported → finalize
      └─ unsupported → retrieve_once_or_correct
  → END
```

Suggested graph state:

```python
RagState:
    original_question
    resolved_question
    strategy
    subquestions
    retrieval_queries
    candidates
    evidence
    evidence_grade
    retrieval_attempts
    draft_answer
    claim_checks
    final_answer
```

Every node should perform one clear job and return structured data. Avoid placing the complete workflow inside one agent prompt.

## 10. Recommended code structure

```text
src/app/rag/
├── __init__.py
├── contracts.py
├── config.py
├── tools.py
├── ingest/
│   ├── __init__.py
│   ├── pipeline.py
│   ├── parsers/
│   └── chunking/
├── indexes/
│   ├── __init__.py
│   ├── vector.py
│   ├── lexical.py
│   ├── document_store.py
│   ├── structured.py
│   └── graph.py
├── retrieve/
│   ├── __init__.py
│   ├── service.py
│   ├── query_analyzer.py
│   ├── hybrid.py
│   ├── fusion.py
│   ├── reranker.py
│   ├── grader.py
│   └── context_builder.py
├── eval/
│   ├── __init__.py
│   ├── evaluate.py
│   ├── datasets.py
│   └── metrics.py
├── generation/
│   ├── answer.py
│   ├── citations.py
│   └── verifier.py
└── graph/
    ├── state.py
    ├── nodes.py
    └── workflow.py
```

Create this structure progressively as functionality is implemented. Do not add empty modules merely to match the diagram.

## Build sequence

### Phase 1 — Parsing foundation

- Create the normalized document contract.
- Create the parser router.
- Add native text/Markdown, Trafilatura, and Docling adapters.
- Preserve page, section, table, and URL metadata.
- Add assisted parsing as a fallback, not the default.

**Result:** heterogeneous documents produce one predictable structured format.

### Phase 2 — Parent-child and multi-representation indexing

- Implement structure-aware child chunks and parent sections.
- Store child embeddings in Chroma.
- Add a lexical index.
- Add a parent document store.
- Add structured table storage where needed.

**Result:** one source can be searched semantically, lexically, and structurally.

### Phase 3 — Query intelligence

- Classify direct versus complex questions.
- Resolve conversational references.
- Add optional decomposition.
- Add optional step-back questions.

**Result:** complex questions become precise retrieval tasks without slowing simple questions.

### Phase 4 — Hybrid retrieval and reranking

- Retrieve dense and lexical candidates.
- Fuse rankings.
- Deduplicate candidates.
- Add local cross-encoder reranking.
- Build the final evidence bundle.

**Result:** the generator receives a small, relevant, diverse evidence set.

### Phase 5 — Corrective retrieval

- Grade evidence as sufficient, partial, or irrelevant.
- Rewrite only missing information needs.
- Add one bounded retrieval retry.
- Add approved web search for missing corpus information.
- Abstain when no reliable evidence exists.

**Result:** weak retrieval triggers controlled correction instead of hallucination.

### Phase 6 — Grounded answers

- Generate from a structured evidence bundle.
- Attach document/page/URL citations.
- Detect conflicting sources.
- Return partial answers when only part of a question is supported.

**Result:** factual claims can be traced back to their evidence.

### Phase 7 — Active retrieval and verification

- Extract claims from the draft.
- Check claim-to-evidence support.
- Search once for a specific unsupported claim.
- Correct, remove, or abstain.

**Result:** the final answer contains no silently unsupported factual claims.

### Phase 8 — LangGraph integration

- Convert the pipeline into typed graph nodes.
- Add conditional routes.
- Enforce retry limits.
- Keep deterministic services outside model prompts.

**Result:** the complete decision path is explicit, bounded, and maintainable.

## Future production hardening

The following are intentionally excluded from the current build sequence and will be handled after the advanced RAG core works:

- queues, retries, and recovery;
- index and document versioning;
- caching and latency monitoring;
- retrieval and answer-accuracy evaluation;
- security and access controls;
- logging, diagnostics, and rollback.

These are still required before deploying DARWIN as a dependable multi-user production service.

## Immediate next step

Begin with **Phase 1 only**: define the normalized `Document` and `Section` contracts, then adapt the existing text ingestion to produce those objects without changing current retrieval behavior.

## References

- [Docling supported formats](https://docling-project.github.io/docling/usage/supported_formats/)
- [Trafilatura documentation](https://trafilatura.readthedocs.io/en/latest/)
- [LlamaParse SDK](https://developers.api.llamaindex.ai/api/python/)
- [LangGraph agentic RAG](https://docs.langchain.com/oss/python/langgraph/agentic-rag)
- [Sentence Transformers retrieve and rerank](https://www.sbert.net/examples/sentence_transformer/applications/retrieve_rerank/README.html)

# MediAssist AI: Enterprise RAG Engine

## 1. Purpose and status

This document describes the Phase 10 Retrieval-Augmented Generation (RAG)
engine. Phase 10 composes ChromaDB retrieval with OpenAI answer generation and
returns the retrieved source passages as citations.

The implementation is a tested learning prototype, **not a production-ready
healthcare service**. In particular, metadata filters are not authorization
controls, local ChromaDB is not a multi-user security boundary, and external
model processing must be approved before any sensitive data is sent.

## 2. Component responsibilities

| Component | Responsibility |
|---|---|
| `vector_store.py` / `ChromaVectorStore` | Persist chunks, embeddings, source details, searchable terms, and caller-supplied scalar metadata. |
| `retriever.py` / `Retriever` | Run semantic, BM25 lexical, and hybrid search; apply ChromaDB metadata filters; return ranked evidence. |
| `rag.py` / `RAGEngine` | Prepare numbered evidence, call OpenAI, validate citation markers, and return the answer with source references. |
| `settings.py` | Load the local `.env` values and keep the embedding-model setting separate from the answer-model setting. |

## 3. End-to-end request flow

1. Index each authorized document with the Phase 5 chunker and Phase 6
   embedding model. Chunks are stored in the Phase 8 ChromaDB collection.
2. The indexer saves normalized, case-insensitive terms with each chunk to
   support lexical candidate filtering. Custom scalar metadata can be attached
   for later filtering.
3. A caller submits a question, retrieval mode, top-K value, and optional
   ChromaDB metadata filter.
4. Before accessing ChromaDB, `RAGEngine` sends the question alone to the
   configured OpenAI model for a strict `IN_SCOPE` / `OUT_OF_SCOPE`
   classification. The classifier checks whether the question concerns
   MediAssist healthcare policies/SOPs, hospital operations, or healthcare
   documents represented in its approved knowledge-base use. It does not
   answer the question.
5. An out-of-scope question receives a fixed polite redirect; the engine does
   not retrieve context or make an answer-generation request. An in-scope
   question continues to retrieval.
6. The `Retriever` runs semantic search, lexical search, or both for hybrid
   search. Filters are applied to each branch before candidates are combined.
7. Hybrid mode fuses vector and lexical rankings with Reciprocal Rank Fusion
   (RRF). The final top-K chunks, source details, and scores are returned.
8. `RAGEngine` formats the highest-ranked chunks as numbered passages and
   assigns matching citation records.
9. The OpenAI Responses API receives the question and formatted passages.
   Instructions require evidence-grounded answers with inline `[n]` citations
   and an explicit insufficient-evidence response when the context does not
   support an answer.
10. The engine rejects citation markers that refer to passages not sent to the
   model, and returns the answer together with citation source paths, chunk
   numbers, retrieval distances, and custom metadata.

If retrieval returns no passages, the engine returns an explicit message and
does not make the answer-generation call. Every question is sent to OpenAI for
scope classification, and every in-scope question with evidence also sends
retrieved passages for answer generation. Both API requests set `store=False`;
this is not a substitute for reviewing provider data-handling terms or
organizational approval.

The scope classifier is a topic gate, not a relevance or authorization
decision. It can misclassify ambiguous questions. For an in-scope question,
retrieval still needs to provide supporting evidence; otherwise the engine
returns an insufficient-sources message without generating an answer.

## 4. Retrieval mechanisms and ranking

The initial final result count is **K = 5**, configurable per question up to
100. Five is a baseline rather than a measured optimum.

### Semantic search

- The question is embedded using the same model recorded in the collection.
- ChromaDB searches the normalized vectors with cosine distance.
- ChromaDB returns nearest neighbors first; lower distance ranks higher.
- The default hybrid candidate pool asks semantic search for up to
  `min(max(4 × K, 20), 100)` candidates before final fusion.

Cosine distance is not a probability, confidence estimate, or clinical
correctness measure.

### Lexical search

- Indexing stores unique, case-folded word tokens in a reserved `terms`
  metadata field. Query tokenization uses the same Unicode word-token rule.
- ChromaDB's metadata `$contains` filter retrieves chunks matching one or more
  query terms; optional user metadata filters are combined with this condition.
- The implementation calculates Okapi BM25 (`k1 = 1.5`, `b = 0.75`) across the
  returned lexical candidate set and orders candidates by that score.
- The lexical candidate set is capped at 1,000 records to bound local work.
  BM25 scores are therefore relative to the retrieved candidate set, not a
  corpus-wide relevance guarantee.

Lexical token matching can help with exact names, identifiers, and policy
terms. It is not a synonym system and is not a separately operated search
service.

### Hybrid retrieval

Hybrid mode combines the two ranked lists with Reciprocal Rank Fusion:

```text
RRF(document) = sum(1 / (60 + rank_in_each_result_list))
```

Documents appearing in both the semantic and lexical lists accumulate both
rank contributions. Results are ordered by descending RRF score, with the
stable ChromaDB record ID as a deterministic tie-breaker, and truncated to
the requested final top-K.

RRF combines positions, not raw cosine distances and BM25 scores. It does not
prove that a passage is relevant. The initial weights are equal because each
list contributes one reciprocal-rank value; tune only through a reviewed
evaluation set.

### Metadata filtering

`metadata_filter` uses ChromaDB's `where` syntax, for example:

```python
{"department": "admissions"}
```

Scalar string, numeric, and boolean fields can be attached during indexing.
The same filter is applied to semantic and lexical search, before fusion.
Internal `terms` metadata is reserved and cannot be queried through the
public filter argument.

Filters are not authorization. The current prototype has no user identity,
tenant boundary, permission lookup, or policy-enforcement layer. Do not rely on
a caller-supplied filter to protect patient or restricted records.

## 5. Citations and answer grounding

Each evidence passage is numbered in rank order (`[1]`, `[2]`, …). The prompt
includes the matching source path and one-based chunk number. The returned
`Citation` includes:

- citation reference;
- source path and one-based chunk number;
- semantic cosine distance when available; and
- stored custom metadata, excluding internal token metadata.

The model is instructed to cite factual claims with the matching reference.
The engine requires at least one numeric citation marker and validates that
each marker points to a supplied passage. This check prevents missing or
fabricated reference numbers; it does **not** verify that every factual claim
is supported by its cited passage. Review answers and sources before
consequential use.

The context is capped at 24,000 characters by default and the answer at 900
output tokens. The highest-ranked evidence is included first; the last passage
may be truncated to stay within the context-character budget.

## 6. Configuration and data handling

Configure these values in the repository-root `.env` file:

```dotenv
OPENAI_KEY=your-openai-api-key
OPENAI_CHAT_MODEL=gpt-4o-mini
DEFAULT_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
```

`OPENAI_KEY` is mapped to the SDK-standard `OPENAI_API_KEY` name by existing
settings code. `OPENAI_CHAT_MODEL` controls answer generation and is distinct
from `DEFAULT_MODEL_NAME`, which controls local embeddings. The `.env` file
must remain local and ignored by Git.

**Every question is sent to the configured OpenAI service for scope
classification. In-scope questions also send retrieved chunk text for answer
generation.** Do not run this pipeline on real patient
information, identifiers, or other sensitive material unless the applicable
organization, data-governance, privacy, security, and provider approvals are
in place. Use authorized non-sensitive sample data for development.

## 7. Running the pipeline

Install the project's embedding extra and index documents with useful
filterable metadata:

```powershell
uv sync --extra embeddings
uv run --extra embeddings python -m mediassist_healthcare.vector_store index "path\to\admission-policy.pdf" --metadata department=admissions --metadata document_type=sop
```

Ask a question using hybrid retrieval and a department filter:

```powershell
uv run --extra embeddings python -m mediassist_healthcare.rag "What documents are needed for admission?" --mode hybrid --top-k 5 --filter department=admissions
```

Choose `semantic`, `lexical`, or `hybrid` with `--mode`. Use `--filter
FIELD=VALUE` more than once for additional equality filters. Specify
`--db-path`, `--collection`, and `--embedding-model` when using non-default
index settings. `--chat-model` overrides the configured OpenAI answer model.
The OpenAI SDK reads the API key from the local environment.

Run all unit tests, including ChromaDB retrieval and mocked answer-generation
tests, with:

```powershell
uv run python -m unittest discover -s tests -v
```

Tests use isolated ChromaDB clients and mocked provider responses; they do not
send queries or documents to OpenAI.

## 8. Evaluation and production gaps

Before changing top-K, RRF settings, candidate limits, or adding thresholds,
evaluate using authorized, reviewed queries and relevant-passage labels.
Consider Recall@K, Precision@K, MRR, groundedness, citation correctness,
latency, and review of incorrect or unsupported responses. Do not use
benchmark claims without measurements on a representative corpus.

Before any production use, separately design and validate:

- authenticated identity, tenant isolation, and per-document authorization;
- safe ingestion and metadata provenance;
- PHI handling, encryption, retention, audit logging, and provider approvals;
- prompt-injection defenses and output safety evaluation;
- robust answer/citation faithfulness evaluation and abstention thresholds;
- model/provider availability, cost, rate limits, retries, monitoring, and
  incident response; and
- backup, restore, lifecycle management, and deployment operations.

The current module is an educational RAG engine foundation, not a certification
or claim of enterprise production readiness.

# MediAssist AI: RAG Retrieval Strategy

## 1. Purpose

This document records the Phase 9 semantic-retrieval baseline for retrieving
document chunks from MediAssist AI's ChromaDB vector store. It describes that
baseline's mechanism, result count, ranking, and evaluation approach. Phase 10
extends retrieval with lexical and hybrid search, metadata filters, citations,
and answer generation; see the [RAG engine documentation](rag-engine.md).

The settings below describe the Phase 9 baseline, not the complete Phase 10
pipeline.

## 2. Current retrieval configuration

| Setting | Phase 9 baseline |
|---|---|
| Vector store | Local persistent ChromaDB collection |
| Embedding model | Same Hugging Face model used to index the collection; configured through `DEFAULT_MODEL_NAME` |
| Query embedding | One normalized vector generated from the user's query |
| Search method | ChromaDB vector similarity using cosine distance |
| Initial top-K | 5 results by default; configurable per search |
| Ranking | ChromaDB nearest-first ordering: lower cosine distance ranks higher |
| Additional reranking | None |
| Keyword/hybrid stage | None |

**Top-K of 5 is a starting configuration, not an experimentally proven
optimum.** It matches the current Phase 8 command default and should be tuned
with representative queries and reviewed relevance labels before any
production decision.

## 3. Retrieval flow

For the Phase 9 semantic baseline, the Phase 8 CLI performs these steps:

1. Read the query text and the selected ChromaDB database and collection.
2. Load the configured local embedding model.
3. Convert the query into a normalized vector. It must use the same model as
   the vectors already stored in the collection; the application rejects a
   model-name mismatch.
4. Ask ChromaDB for up to `top_k` nearest vectors using the query embedding.
   The collection uses cosine distance.
5. Receive each matching chunk's text, source path, chunk position, and
   distance.
6. Display the results in the order returned by ChromaDB, with the source,
   one-based chunk number, and distance.

If fewer than `top_k` chunks are available, ChromaDB returns the available
matches. If the collection has no matching records, the CLI reports that no
indexed chunks were found.

## 4. How ranking works

ChromaDB ranks vector matches by the configured cosine distance. For normalized
vectors, cosine distance is `1 - cosine similarity`:

- A **smaller distance** means the query vector is more similar to the chunk
  vector and the chunk appears earlier in the results.
- A **larger distance** means the vectors are less similar.
- A distance is a similarity measure for this embedding space, **not** a
  probability, confidence score, clinical relevance guarantee, or proof that
  the chunk answers the query.

The Phase 9 baseline relies on ChromaDB's nearest-first result order. Phase 10
adds hybrid rank fusion and caller-provided metadata filters, but does not
deduplicate results from the same source or rerank chunks with a separate
cross-encoder model.

## 5. Selecting and tuning top-K

The initial value is **K = 5**. Increasing K can expose more supporting
context, but may also include less relevant chunks and make a future answer
longer or noisier. Decreasing K can reduce irrelevant context, but may omit
useful evidence. The right value depends on chunking, query type, source
documents, and the later answer-generation context limit.

Tune K using a small, authorized evaluation set:

1. Prepare representative natural-language and exact-term queries.
2. Have a qualified reviewer mark which chunks or source passages are relevant
   to each query. Do not use real patient information in this learning
   prototype.
3. Run the same queries with several K values (for example, 3, 5, and 10).
   These are evaluation candidates, not additional production defaults.
4. Compare **Recall@K** (whether relevant chunks appear in the first K results)
   and **Precision@K** (how many returned chunks are relevant). Optionally
   measure **MRR** (how highly the first relevant chunk is ranked).
5. Review the actual text and source paths with a domain-qualified reviewer.
   A metric cannot establish clinical safety or correctness.
6. Record the embedding model, chunking settings, ChromaDB version, queries,
   K, and relevance judgments so comparisons are reproducible.

Keep K configurable at query time. Change the default only after evaluation
shows a useful, repeatable trade-off on an authorized representative corpus.

## 6. Running the baseline

Index a document before searching. Both operations must use the same database,
collection, and embedding model:

```powershell
uv sync --extra embeddings
uv run --extra embeddings python -m mediassist_healthcare.vector_store index "path\to\your-document.pdf"
uv run --extra embeddings python -m mediassist_healthcare.vector_store search "How does the admission process work?" --top-k 5
```

The Phase 8 search command defaults to K = 5. Set another positive `--top-k`
value to evaluate a different result count. Use the same `--db-path`,
`--collection`, and `--model` values used for indexing when overriding the
defaults.

## 7. Phase 9 limits and later retrieval improvements

- **Phase 9 was vector-only:** exact terms, policy numbers, and abbreviations
  did not have a separate lexical search branch. Phase 10 adds lexical and
  hybrid retrieval; see the linked RAG engine document for its candidate
  limits and Reciprocal Rank Fusion behavior.
- **No cross-encoder reranking:** Phase 10 fuses semantic and lexical ranks,
  but does not score candidate pairs with a separate reranking model.
- **Metadata filters are not authorization:** Phase 10 supports caller-supplied
  ChromaDB metadata filters, but the prototype has no user identity, role,
  tenant, or access-control enforcement.
- **Chunk-level results:** overlapping or adjacent chunks can repeat context.
  Phase 10 does not merge neighboring chunks or deduplicate by source.
- **No relevance threshold:** the CLI returns the nearest available results
  even when all distances may be poor. Reviewers must not treat a non-empty
  result list as evidence that the query was answered.
- **Local prototype only:** authorization, production access controls,
  sensitive-data handling, monitoring, and service operations require separate
  design and validation.

Possible later improvements include permission-enforced filtering,
adjacent-chunk expansion, a cross-encoder reranker, and a reviewed
minimum-relevance policy. Evaluate them as separate changes; do not imply
they are already implemented.

## 8. Safety and source review

Retrieved text is untrusted reference material. The Phase 10 answer generator
preserves source references and is instructed not to follow instructions
embedded in retrieved documents or invent unsupported answers; prompt
instructions alone do not guarantee safe behavior. Clearly communicate when
evidence is missing or conflicting. Qualified reviewers must validate
consequential healthcare use. The pipeline is an educational prototype, not a
clinical decision system.

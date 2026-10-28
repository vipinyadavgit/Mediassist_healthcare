# MediAssist AI: Vector Database Comparison

## 1. Purpose and scope

This Phase 7 document compares ChromaDB, Pinecone, Weaviate, and FAISS for the
MediAssist AI retrieval pipeline. It covers index approaches, keyword/vector/
hybrid search, persistence and metadata, deployment, and the project's target
of fewer than one million vectors.

This is a qualitative comparison based on the official documentation linked
below. No MediAssist benchmark has been run, so the comparison does not claim
that one product is faster or more accurate on our corpus.

## 2. Project context

The current Phase 6 embedding model, `sentence-transformers/all-MiniLM-L6-v2`,
produces 384-dimensional vectors. Phase 6 returns normalized vectors but does
not persist them. The system will also need to retain chunk text and source
metadata so a retrieved result can be shown with its document reference.

**Project decision:** ChromaDB is selected for Phase 8. The implementation uses
a local persistent collection and the project's existing Phase 6 embeddings.
This is a project direction based on the desired local learning workflow, not
a measured performance winner.

## 3. What is being compared?

These options are not all the same kind of product:

- **FAISS** is a vector similarity search library. The application assembles
  the surrounding database features, such as document text storage, metadata,
  keyword search, filtering, and lifecycle management.
- **ChromaDB** is a database focused on AI retrieval. It stores documents,
  embeddings, and metadata and offers local/self-hosted and hosted options.
- **Pinecone** is a managed vector database service. It offers vector APIs and
  document-oriented indexing with text and vector search capabilities.
- **Weaviate** is a vector database that can be self-hosted or used as a
  managed service. It supports vector, BM25 keyword, and hybrid search.

## 4. Indexing and search comparison

| Option | Indexing approaches described in official docs | Keyword search | Vector search | Hybrid search |
|---|---|---|---|---|
| **ChromaDB** | Single-node collections use HNSW approximate nearest-neighbor indexing. HNSW parameters include distance space, construction/search candidate sizes, and maximum neighbors. | Document `$contains` and regex filters are available; the documented `$contains` search is case-sensitive. This is not identical to a general-purpose BM25 search engine. | Dense vector similarity with configurable distance space such as cosine, inner product, or L2. | Chroma documents dense, sparse, and hybrid search capabilities. Confirm the chosen Chroma deployment, API, and version support the exact combination needed. |
| **Pinecone** | Managed indexes. The vector-index API supports dense and sparse vectors. The document-index API uses a schema with dense vectors, sparse vectors, and full-text-search fields. | Document indexes support full-text search using BM25 over configured string fields. | Dense-vector semantic search; document indexes can also use integrated embedding where configured. | Document indexes can combine text and semantic signals through filtering or reciprocal-rank fusion; vector indexes support dense-plus-sparse patterns. |
| **Weaviate** | HNSW is a common approximate-nearest-neighbor index; configuration is available for vector-index behavior. | BM25 keyword search. | Vector similarity search over supplied or provider-generated vectors. | Runs vector and BM25 searches and combines their results. Fusion options include relative-score and ranked fusion; alpha controls the vector/keyword weighting. |
| **FAISS** | Offers exact flat search (`IndexFlatL2`, `IndexFlatIP`), graph search such as `IndexHNSWFlat`, and inverted-file/quantized families such as IVF and PQ. These trade accuracy, speed, and memory differently. | Not a text-search engine. The application must add a lexical index or keyword-search library. | Dense nearest-neighbor search, including exact and approximate index choices. | The application must run keyword and vector search separately and combine results (for example, using reciprocal-rank fusion). |

### Practical interpretation

- **Exact search** compares a query with every stored vector. It is simple and
  useful as a small-scale quality baseline, but work grows with the collection.
- **Approximate nearest-neighbor (ANN) search** uses an index such as HNSW or
  IVF to search fewer candidates. It can reduce search work, with trade-offs
  between recall, latency, memory, and index-building cost.
- **Keyword search** is useful when the exact token matters, such as a
  medication name, department code, policy identifier, or lab abbreviation.
- **Vector search** is useful when a user expresses the same idea with
  different wording.
- **Hybrid search** combines lexical and semantic evidence. A hybrid score
  must be interpreted and evaluated; it does not automatically make results
  correct or safe.

## 5. Storage, metadata, and operations

| Option | Persistence and metadata | Operational model | Main application responsibility |
|---|---|---|---|
| **ChromaDB** | Collections hold embeddings, documents, and metadata; local persistent clients and hosted/self-managed modes are documented. Metadata and document filters are available. | Convenient for local development; deployment and scaling choices depend on whether it is run locally, self-hosted, or as a service. | Choose persistence and backup locations, enforce access controls, and validate filters and version-specific search features. |
| **Pinecone** | Managed indexes store vector/document records and support metadata filters; document-index schemas can include searchable text fields. | Managed cloud service. Requires network access, service configuration, credentials, and cost review. | Manage API credentials, namespaces/tenancy, data governance, provider availability, and service costs. |
| **Weaviate** | Objects and properties are stored with vectors; supports metadata/property filtering. | Can be self-hosted or managed. Requires service configuration and operational monitoring for self-hosting. | Operate or pay for the service, manage schema and vectorizer configuration, and control provider integrations. |
| **FAISS** | Indexes hold vectors and IDs; FAISS supports writing and reading index files. It does not provide a complete document and metadata database. | Embedded library in the application process; no separate vector database service is required. | Persist and back up the index, map vector IDs to chunk text/source metadata, implement filtering and keyword/hybrid search, and manage updates/deletes. |

## 6. Suitability below one million vectors

“Under one million vectors” is not enough information to make a performance
claim. Feasibility depends on vector dimensions, data type, chosen index,
metadata and text size, filters, query rate, concurrency, hardware, and the
acceptable recall/latency balance. All four options can be considered for this
range, but they do not have the same operational or application requirements.

### Raw vector memory estimate

For the current 384-dimensional model, a single float32 vector uses:

```text
384 dimensions × 4 bytes = 1,536 bytes per vector
1,000,000 vectors × 1,536 bytes ≈ 1.43 GiB of raw vector values
```

This estimate excludes index structures, IDs, metadata, document text,
database overhead, caches, process memory, and backups. For example, an HNSW
graph uses additional memory, while quantized FAISS indexes may use less vector
memory at the cost of approximation or precision. Do not treat 1.43 GiB as a
full deployment sizing figure.

### Scale-focused trade-offs

- **FAISS** makes index choice and vector search behavior explicit. Flat search
  is a useful exact baseline; HNSW or IVF/PQ can be tested as ANN alternatives.
  The application must supply the database features around the index.
- **ChromaDB** provides a more complete local retrieval workflow with stored
  documents/metadata and an HNSW-based single-node vector index. This can
  reduce integration work for a local prototype, but memory and query behavior
  still need to be measured with the project's data and filters.
- **Pinecone** and **Weaviate** provide service-oriented operation and richer
  database features, but add cloud/self-hosting, credentials, network,
  governance, and cost considerations that may be unnecessary for a local
  learning prototype.

No product-specific one-million-vector guarantee is inferred here. Measure
with representative vector dimensions, actual metadata, realistic top-K,
filters, and the target hardware/deployment.

## 7. Qualitative fit for MediAssist AI

| Criterion | ChromaDB | Pinecone | Weaviate | FAISS |
|---|---|---|---|---|
| Beginner setup for local prototype | Strong | Lower; service setup required | Moderate; server/service setup | Moderate; API itself is small, but surrounding storage/search must be built |
| Bring-your-own Phase 6 embeddings | Yes | Yes | Yes | Yes |
| Stored text and metadata alongside vectors | Built in | Supported, especially document indexes | Supported | Application-managed |
| Keyword search without a separate app component | Basic document filters; verify requirements | Full-text/BM25 on document-index schema | BM25 | No |
| Built-in hybrid retrieval options | Documented; verify deployment/API version | Yes, with API-specific patterns | Yes, with configurable fusion | No; implement in the application |
| Local operation | Yes | No, managed service | Yes | Yes |
| Infrastructure/credentials burden | Low for local use | Cloud account, credentials, cost | Depends on self-hosted vs managed | Low service burden; higher application engineering burden |
| Selected for MediAssist Phase 8 | **Yes** | No | No | No |

## 8. MediAssist AI decision

**Selected for Phase 8: ChromaDB with a local persistent client.** This option
fits the current learning goal of persisting vectors together with chunk text
and source metadata, without building those database features around a lower-
level vector index. The Phase 8 CLI indexes one document at a time and
performs vector similarity search using the same configured embedding model.

The default database directory is `output/chroma_db`, which is ignored by Git.
The collection uses cosine distance. This selection is not a benchmark result
and does not establish production readiness; performance, backup, access
control, and deployment requirements must be assessed separately before use
with sensitive or production data.

## 9. Suggested fair comparison experiment

Before calling a choice “faster” or “better,” use a small authorized sample and
the same inputs for each candidate:

1. Use the same Phase 5 chunks and Phase 6 vectors for all systems.
2. Store identical chunk IDs, source references, and metadata.
3. Use a reviewed set of natural-language queries, exact-term queries, and
   department/policy filters.
4. Compare vector-only, keyword-only, and hybrid results where each system
   supports them; document any application-side fusion code used for FAISS.
5. Measure index-build time, query latency at the same top-K, memory/disk use,
   result recall against reviewed relevant chunks, and operational setup.
6. Record software versions, index settings, hardware, dataset size, and
   environment. Never include real patient text or identifiers in the report.

Until that experiment is run, present product fit as qualitative and do not
claim a benchmark result.

## 10. References

Official documentation consulted:

- [Chroma introduction](https://docs.trychroma.com/docs/overview/introduction)
- [Chroma collection configuration and HNSW settings](https://docs.trychroma.com/docs/collections/configure)
- [Chroma full-text and document filtering](https://docs.trychroma.com/docs/querying-collections/full-text-search)
- [Pinecone indexing overview](https://docs.pinecone.io/guides/index-data/indexing-overview)
- [Pinecone hybrid search](https://docs.pinecone.io/guides/search/hybrid-search)
- [Weaviate vector search](https://docs.weaviate.io/weaviate/concepts/search/vector-search)
- [Weaviate hybrid search and fusion](https://docs.weaviate.io/weaviate/concepts/search/hybrid-search)
- [FAISS overview](https://github.com/facebookresearch/faiss/wiki)
- [FAISS index types](https://github.com/facebookresearch/faiss/wiki/Faiss-indexes)

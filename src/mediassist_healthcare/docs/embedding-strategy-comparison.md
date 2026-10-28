# MediAssist AI: Embedding Strategy Comparison

## Purpose

This document records the Phase 6 embedding approach, alternatives considered,
setup and privacy trade-offs, and the current implementation's limitations.
The comparison is qualitative; no retrieval-quality or speed benchmark has
been run yet.

## What an embedding does

An embedding model converts a piece of text into a list of numbers called a
vector. Texts with related meaning are intended to have vectors that are close
to one another under a similarity measure. Later project phases can store
document vectors and compare a user's query vector with them to retrieve
relevant chunks.

Phase 6 embeds the chunks produced by Phase 5. It does not save vectors or
perform vector search.

## Options considered

| Option | Benefits | Trade-offs | Fit for this project |
|---|---|---|---|
| Local Hugging Face Sentence Transformers | Straightforward model loading and batch encoding; no per-request embedding API; after the model is downloaded, text can be embedded locally. | PyTorch and model files are large dependencies/downloads; local CPU/GPU resources determine throughput; model quality must be evaluated on the project corpus. | **Selected** for an educational prototype because it keeps the embedding step understandable and local. |
| Hugging Face Transformers with custom pooling | Direct access to tokenizer and model components; can customize tokenization and pooling. | The developer must implement attention-mask-aware pooling, normalization, batching, and validation correctly. This creates more code to learn and maintain. | Useful for learning model internals, but not the simplest reliable first implementation. |
| Hosted embedding API | Avoids downloading and serving a model locally; provider manages model infrastructure. | Sends text to a third party; requires credentials and network access; introduces provider cost, rate limits, and service dependency. Healthcare data requires explicit privacy, security, contractual, and governance review before use. | Not selected for the local prototype. Could be evaluated later with approved, non-sensitive data and an approved provider. |
| TensorFlow-compatible model/runtime | TensorFlow can run compatible text-embedding models. | The selected Sentence Transformers Python interface uses its PyTorch backend. A TensorFlow path would require a compatible model and a different library or custom tokenization/pooling implementation; it is not a switch of one install option. | Possible future alternative, but not the approved Phase 6 path. |

### Why PyTorch for this implementation?

Hugging Face is the model hub; PyTorch and TensorFlow are machine-learning
frameworks that can run models. The `sentence-transformers` library provides
the high-level `SentenceTransformer` API selected here, and its normal inference
path uses PyTorch. It handles tokenization, model execution, pooling, batching,
and embedding output for us.

TensorFlow is not inherently unsuitable. However, using it would mean selecting
a compatible TensorFlow implementation and likely writing or adopting a
different embedding pipeline. For this phase, using Sentence Transformers with
PyTorch keeps the code small and avoids implementing pooling incorrectly.

## Selected model

The initial model is
[`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2).
Its Hugging Face model card describes it as a sentence and short-paragraph
encoder that produces **384-dimensional** vectors for semantic search,
clustering, and similarity. The model card notes that inputs longer than 256
word pieces are truncated. This is a general English model, not a medical
domain-specialized model.

### Other model candidates

These are candidates for a later, measured comparison. The details below come
from their Hugging Face model cards; published results on other datasets are
not MediAssist evaluation results.

| Candidate | Model-card details | What to consider |
|---|---|---|
| [`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | General sentence/short-paragraph embeddings; 384 dimensions; inputs longer than 256 word pieces are truncated. | Selected as the simple baseline. Its general-domain training does not guarantee strong retrieval of hospital terminology. |
| [`intfloat/e5-small-v2`](https://huggingface.co/intfloat/e5-small-v2) | English text embeddings; 384 dimensions; up to 512 tokens; retrieval inputs should use `query: ` and `passage: ` prefixes. | Longer model-card context window, but the code must apply different prefixes consistently to queries and document chunks. |
| [`neuml/pubmedbert-base-embeddings`](https://huggingface.co/NeuML/pubmedbert-base-embeddings) | Fine-tuned from PubMedBERT; 768 dimensions; model configuration lists a 512-token sequence length; trained using PubMed title/abstract pairs. | Biomedical-literature alignment makes it an important candidate to test. Its larger vectors and literature focus do not guarantee better results on hospital SOPs, patient records, or this project's specific data. |

The model is a starting point, not a clinical-quality guarantee. We must test
retrieval on representative, authorized project documents and queries. Chunk
size, tokenizer truncation, language coverage, and domain terminology can all
affect results. Do not treat vector similarity as clinical correctness.

The code requests normalized embeddings. Unit-length vectors allow dot product
similarity to correspond to cosine similarity, which is useful for later
retrieval. The current module returns Python lists for clarity and does not
persist or log the source text or embedding values.

## Dependency and model downloads

The embedding library is an optional dependency so the regular project setup
does not download PyTorch for users who are not working on Phase 6:

```powershell
uv sync --extra embeddings
```

The repository-root `.env` file configures local settings and may contain
credentials. Set `DEFAULT_MODEL_NAME` to choose the default Hugging Face model.
The `--model` command-line option overrides this setting for a single run.
`OPENAI_KEY` is loaded and also exposed as `OPENAI_API_KEY` for code that uses
the OpenAI SDK; the Phase 6 local embedder does not call OpenAI or use that key.
The root `.env` file is ignored by Git. Never paste real keys into source code,
documentation, test fixtures, or terminal commands.

The first model use downloads model files from Hugging Face and caches them on
the local machine. This may take time and disk space. Later runs normally reuse
the cached files. On CPU, embedding speed depends on the computer and batch
size. GPU acceleration may be available when a compatible PyTorch/CUDA setup
is present, but this project does not require a GPU.

## Run and inspect the pipeline

Run one PDF, DOCX, or TXT file per command. Use only approved documents; do not
send real patient information to unapproved services.

```powershell
uv run --extra embeddings python -m mediassist_healthcare.embeddings "path\to\document.pdf" --strategy paragraph --max-chars 1000 --batch-size 32
```

The command reads `DEFAULT_MODEL_NAME` from the repository-root `.env` by
default. Pass `--model "another/model-id"` to temporarily select a different
model without editing `.env`.

The command reports the source path, chunk strategy, number of chunks, selected
model, number of vectors, and vector dimensions. It does not print document
contents or save vectors.

To try a different compatible Hugging Face Sentence Transformers model, use
the `--model` option. Different models may require different query/document
instructions or preprocessing; evaluate the model's own documentation before
using it.

## Reproducibility and evaluation plan

No model comparison benchmark is claimed in this document. To make a future
comparison meaningful:

1. Select a small, approved set of representative SOPs, policies, and clinical
   documents.
2. Keep the same extracted text, chunk boundaries, and evaluation queries for
   each candidate model.
3. Measure embedding setup time, batch throughput, memory use, and vector
   dimensions on the same machine.
4. Evaluate retrieval using reviewed relevant-source labels, including
   Recall@K or another agreed retrieval metric.
5. Record model ID/revision, package versions, settings, dataset description,
   and results. Do not put patient text or identifiers in the report.
6. Have a qualified domain reviewer assess whether retrieved evidence is
   appropriate; embedding similarity alone is not a safety measure.

## References

- [all-MiniLM-L6-v2 model card](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2)
- [E5-small-v2 model card](https://huggingface.co/intfloat/e5-small-v2)
- [PubMedBERT embeddings model card](https://huggingface.co/NeuML/pubmedbert-base-embeddings)
- [Sentence Transformers installation guide](https://sbert.net/docs/installation.html)
- [Sentence Transformers semantic similarity guide](https://sbert.net/docs/sentence_transformer/usage/semantic_textual_similarity.html)

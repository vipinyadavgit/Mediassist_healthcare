# MediAssist AI

**An enterprise healthcare AI copilot built step by step.**

MediAssist AI brings hospital knowledge, structured operational data, and medical documents together in one assistant. The project is being developed incrementally so each capability can be understood, implemented, and tested before the next phase begitns.

> **Scope note:** This is an educational prototype. AI-generated information is decision support, not a diagnosis or a replacement for qualified healthcare professionals.

## What the project is designed to do

- Search hospital policies, SOPs, and other healthcare documents with RAG.
- Read uploaded PDFs, DOCX files, and text files, then process images and reports.
- Retrieve authorized patient and operational information through MCP tools.
- Coordinate specialized agents and present evidence-grounded answers.
- Evaluate answer quality, safety, and system performance.

## Technology direction

| Area                   | Planned technology                            |
| ---------------------- | --------------------------------------------- |
| Language               | Python                                        |
| Document ingestion     | pypdf, python-docx                            |
| Embeddings             | Hugging Face models                           |
| Retrieval              | ChromaDB semantic, lexical, and hybrid search |
| RAG answer generation  | OpenAI Responses API with source citations    |
| Agent workflow         | LangGraph                                     |
| User interface         | Streamlit                                     |
| API                    | FastAPI                                       |
| Structured data access | PostgreSQL through an MCP server              |
| Deployment             | Docker and Azure Container Apps               |

Components will be introduced in their project phase; not every listed capability is implemented yet.

## Project status and learning roadmap

Phases 1–3 (requirements, architecture, and project setup) are complete. Development proceeds one phase at a time, with review before file changes for each phase.

| Phase | Focus                        | Learning outcome / deliverable                                                | Status   |
| ----: | ---------------------------- | ----------------------------------------------------------------------------- | -------- |
|     4 | Document ingestion           | Load one PDF, DOCX, or TXT file per request                                   | Complete |
|     5 | Text processing and chunking | Clean text and compare chunking strategies                                    | Complete |
|     6 | Embedding pipeline           | Compare embedding options and create local Hugging Face embeddings            | Complete |
|     7 | Vector database comparison   | Compare indexing and keyword, vector, and hybrid search for the project scale | Complete |
|     8 | Vector database setup        | Persist document chunks and embeddings in ChromaDB and search them            | Complete |
|     9 | Retrieval strategy           | Document top-K retrieval, ranking, and selection                              | Complete |
|    10 | Enterprise RAG               | Semantic and hybrid retrieval, metadata filters, citations, and RAG engine    | Complete |
|    11 | Streamlit frontend           | Build chat and file-upload workflows                                          | Complete |
|    12 | FastAPI backend              | Expose chat and upload APIs                                                   | Current  |

The project tracker remains the source of truth for detailed tasks, deliverables, and status.

## Setup

### Prerequisites

- Python 3.13 or newer
- [uv](https://docs.astral.sh/uv/)
- Git

From the repository root, create the virtual environment and install the
project plus its direct libraries from `requirements.txt`:

```powershell
uv venv
uv pip install --python .venv\Scripts\python.exe -e . -r requirements.txt
```

`requirements.txt` lists only the main libraries used directly by the project.
`uv` installs their required supporting packages automatically. After changing
the list, rerun the same install command to update the environment.

### Local environment variables

Create a repository-root `.env` file for local configuration. Keep real
credentials in this file, not in Python source or documentation:

```dotenv
OPENAI_KEY=your-openai-api-key
OPENAI_CHAT_MODEL=gpt-4o-mini
DEFAULT_MODEL_NAME=sentence-transformers/all-MiniLM-L6-v2
```

The `.env` file is ignored by Git. The application loads `OPENAI_KEY` as
`OPENAI_API_KEY` for the Phase 10 OpenAI SDK. `OPENAI_CHAT_MODEL` configures
answer generation; `DEFAULT_MODEL_NAME` configures local Hugging Face
embeddings. Phase 6 embedding generation remains local. Phase 10 sends the
question and retrieved document chunks to OpenAI; do not use patient or other
sensitive data without explicit organizational and provider approval.

## Run the document loader

Phase 4 accepts **one file per command**. Supported formats are PDF, DOCX, and UTF-8 TXT.

```powershell
uv run mediassist-ingest "path\to\your-document.pdf"
```

Use the corresponding `.docx` or `.txt` path for other supported formats. The command prints source metadata and extracted text. Batch ingestion, chunking, and indexing are later phases.

## Clean and chunk a document

Phase 5 cleans document text and supports paragraph-first, sentence, and fixed-character chunking. The paragraph-first strategy is the recommended starting default: it keeps paragraphs together when possible and prefers sentence boundaries when splitting long paragraphs. Chunk limits currently use characters, so they must be evaluated against the selected embedding model before being finalized. See the [chunking strategy comparison](src/mediassist_healthcare/docs/chunking-strategy-comparison.md) for the reasoning, limitations, and comparison commands. Processing is still **one file per command**.

```powershell
uv run python -m mediassist_healthcare.text_processing "path\to\your-document.pdf" --strategy paragraph --max-chars 1000
```

Choose `paragraph`, `sentence`, or `character` for `--strategy`. Fixed-character chunks use a default overlap of 100 characters; set `--overlap 0` to disable it or choose another value smaller than `--max-chars`.

## Create text embeddings

Phase 6 uses a local Hugging Face Sentence Transformers model. Install its optional dependency (including PyTorch) when you are ready to run embeddings:

```powershell
uv sync --extra embeddings
```

The first run also downloads the model from Hugging Face; later runs use the local cache. By default, the pipeline reads `DEFAULT_MODEL_NAME` from `.env` (falling back to `sentence-transformers/all-MiniLM-L6-v2`), processes one source document at a time, and reports vector count and dimensions. This embedding-only command does not save vectors; use the Phase 8 ChromaDB command below to persist and search them. The `--model` option overrides the configured model for one run.

```powershell
uv run --extra embeddings python -m mediassist_healthcare.embeddings "path\to\your-document.pdf" --strategy paragraph --max-chars 1000 --batch-size 32
```

See the [embedding strategy comparison](src/mediassist_healthcare/docs/embedding-strategy-comparison.md) for the model choice, alternatives, privacy notes, limitations, and a future evaluation plan.

## Compare vector databases

The Phase 7 qualitative comparison of ChromaDB, Pinecone, Weaviate, and FAISS
is complete. It evaluates options for the project's target of fewer than one
million vectors, including indexing, keyword/vector/hybrid search, metadata,
persistence, deployment trade-offs, and what to measure before choosing. It
does not claim benchmark results. See the [vector database
comparison](src/mediassist_healthcare/docs/vector-database-comparison.md).

ChromaDB is selected for Phase 8. To install the direct libraries listed in
`requirements.txt`, use the setup command above.

## Store and search document chunks

Phase 8 uses ChromaDB's local persistent client. Index one PDF, DOCX, or TXT
document at a time; the command applies Phase 5 chunking, creates Phase 6
embeddings, and stores the chunk text and source details alongside each vector.
The default database is saved under the Git-ignored `output/chroma_db` folder.
The embedding model selected for a collection is recorded and must also be
used for searches.

Install the optional local embedding model support if needed:

```powershell
uv sync --extra embeddings
```

Index a document and then search the stored chunks:

```powershell
uv run --extra embeddings python -m mediassist_healthcare.vector_store index "path\to\your-document.pdf"
uv run --extra embeddings python -m mediassist_healthcare.vector_store search "How does the admission process work?" --top-k 5
```

Attach scalar metadata at indexing time for use in Phase 10 filters:

```powershell
uv run --extra embeddings python -m mediassist_healthcare.vector_store index "path\to\your-document.pdf" --metadata department=admissions --metadata document_type=sop
```

Use `--db-path` to choose another local ChromaDB directory and `--collection`
to select a collection. Both commands use `DEFAULT_MODEL_NAME` from `.env`
unless `--model` is supplied. Search results show ChromaDB cosine distance;
lower distances indicate closer matches, not a guarantee of answer correctness.
Only index authorized documents, and do not use real patient information in
this learning prototype.

## Phase 9: retrieval strategy

The Phase 9 baseline retrieves up to five chunks per query, ordered by
ChromaDB cosine distance (lower distance ranks higher). `--top-k` can be
changed for evaluation. This is a starting point, not a measured optimum; the
Phase 10 engine now adds lexical/hybrid retrieval and answer generation. See
the [RAG retrieval strategy](src/mediassist_healthcare/docs/retrieval-strategy.md)
for the baseline mechanism and top-K evaluation plan.

## Phase 10: Enterprise RAG engine

The Phase 10 engine combines semantic vector search and BM25 lexical search.
Hybrid mode fuses their rankings with Reciprocal Rank Fusion (RRF); the
initial final top-K is 5. Optional ChromaDB metadata filters are applied to
both retrieval branches. The engine sends retrieved passages to the configured
OpenAI model, requests an evidence-grounded answer with numbered citations,
and returns source paths and chunk numbers. Before retrieval, an OpenAI scope
check declines unrelated topics; healthcare questions without supporting
indexed evidence receive a separate insufficient-sources message. The scope
check adds an API call and sends the question to OpenAI. See the [RAG engine
documentation](src/mediassist_healthcare/docs/rag-engine.md) for architecture,
ranking details, filters, privacy considerations, and limitations.

Index documents with filterable metadata, then ask a question:

```powershell
uv sync --extra embeddings
uv run --extra embeddings python -m mediassist_healthcare.vector_store index "path\to\admission-policy.pdf" --metadata department=admissions --metadata document_type=sop
uv run --extra embeddings python -m mediassist_healthcare.rag "What documents are needed for admission?" --mode hybrid --top-k 5 --filter department=admissions
```

Choose `semantic`, `lexical`, or `hybrid` using `--mode`. Filters apply only to
metadata present when a document was indexed and are **not access controls**.
Documents indexed before the Phase 10 lexical-term metadata was added must be
re-indexed before lexical or hybrid retrieval can use their terms. Use only
authorized, non-sensitive sample data unless data processing has received
explicit approval.

## Phases 11–12: Streamlit frontend and FastAPI backend

The standalone Streamlit interface follows the provided template: a left-hand
sidebar for document and image sources, and a MediAssist chat area. Add one
PDF, DOCX, or TXT document per upload action, or one PNG, JPG, JPEG, or WEBP
image per action. Added source names appear below their upload sections and
can be removed from the current session. The chat retains at most five complete
question/answer pairs, dropping the oldest pair first (FIFO).

The UI connects to the Phase 12 FastAPI backend. Document uploads are
extracted, chunked, embedded locally, and indexed in ChromaDB. Image uploads
are stored and can be removed, but are not analyzed with OCR or vision in this
phase. Chat and search are restricted to documents uploaded in that browser
session. The chat continues to show at most five complete question/answer
pairs, dropping the oldest pair first.

Install dependencies once:

```powershell
uv sync --extra embeddings
```

Start the backend and frontend in **separate terminals**, from the repository
root:

```powershell
uv run mediassist-api
```

```powershell
uv run streamlit run src\mediassist_healthcare\frontend.py
```

The API listens on `http://127.0.0.1:8000` by default. Configure
`MEDIASSIST_API_URL` in `.env` if the backend uses another local address.
Interactive API documentation is available at `http://127.0.0.1:8000/docs`.
See the [backend API guide](src/mediassist_healthcare/docs/backend-api.md) for
endpoints, storage behavior, and prototype limitations.

## Run tests

```powershell
uv run python -m unittest discover -s tests -v
```

## Repository layout

```text
src/mediassist_healthcare/   Application package and phase implementations
tests/                       Automated tests
src/mediassist_healthcare/docs/   Project implementation and comparison documents
Project Doc/                 Capstone brief, tracker, and source materials
README.md                    Project overview, setup, and learning roadmap
```

## Safety and data handling

- Use only authorized project datasets and documents.
- Do not commit credentials, secrets, or real patient information.
- Patient-data access will be mediated by role-aware MCP tools; AI agents must not connect directly to PostgreSQL.
- Validate AI outputs against sources and have qualified people review consequential clinical decisions.

## Next step

Phase 12 is in progress: validate the connected frontend and backend using
authorized, non-sensitive sample documents before adding OCR or other
multimodal processing.

# MediAssist FastAPI Backend

## Purpose and scope

Phase 12 exposes the Phase 10 RAG engine and Phase 11 Streamlit workflows
through a local FastAPI service. The UI and backend run as separate processes;
the Streamlit server calls the API server over HTTP.

The implementation is a local learning prototype, not a production healthcare
service. It has no authentication, authorization, tenant security, rate
limiting, audit logging, or production PHI controls. Session identifiers are
random browser-session UUIDs used for accidental data separation, **not an
authorization boundary**. Use only authorized, non-sensitive sample data.

## Run locally

Install the project's dependencies and local embedding model support:

```powershell
uv sync --extra embeddings
```

Start the API and Streamlit UI in separate terminals from the repository root:

```powershell
uv run mediassist-api
```

```powershell
uv run streamlit run src\mediassist_healthcare\frontend.py
```

The API listens on `http://127.0.0.1:8000`; its interactive OpenAPI page is
`http://127.0.0.1:8000/docs`. Set `MEDIASSIST_API_URL` in `.env` to override
the URL used by Streamlit.

## API contracts

All upload, source, search, and chat endpoints use a UUID `session_id` in the
path. Each multipart upload contains one `file` field.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Check API process health without loading AI models. |
| `POST` | `/api/sessions/{session_id}/documents` | Accept one PDF, DOCX, or TXT file; extract text, chunk, embed locally, and index in ChromaDB. |
| `POST` | `/api/sessions/{session_id}/images` | Store one PNG, JPG, JPEG, or WEBP file for source management. No OCR or vision processing is performed. |
| `GET` | `/api/sessions/{session_id}/sources` | List the documents and images uploaded in that session. |
| `DELETE` | `/api/sessions/{session_id}/sources/{file_id}` | Remove the selected file and, for documents, its session-owned ChromaDB chunks. |
| `POST` | `/api/sessions/{session_id}/search` | Retrieve up to 100 chunks using `semantic`, `lexical`, or `hybrid` mode. |
| `POST` | `/api/sessions/{session_id}/chat` | Run the scope check, session-filtered RAG retrieval, and grounded answer generation. |

Search request:

```json
{
  "query": "What documents are needed for admission?",
  "mode": "hybrid",
  "top_k": 5
}
```

Chat request:

```json
{
  "question": "What documents are needed for admission?",
  "mode": "hybrid",
  "top_k": 5
}
```

Both endpoints validate `top_k` in the range 1–100. Chat returns a status
(`answered`, `out_of_scope`, or `insufficient_evidence`) and source citations.
Server filesystem paths and internal session metadata are not returned.

## Storage and deletion

- Uploaded files are stored under the Git-ignored `output/mediassist_api/uploads`
  directory, partitioned by session and generated file ID.
- A local SQLite catalog records source names and upload details so the UI can
  restore its source lists after a rerun.
- Document chunks are indexed in the existing local ChromaDB collection with
  `session_id`, `upload_id`, and original filename metadata.
- Every API search and chat retrieval applies the session ID as a metadata
  filter. This prevents accidental cross-session retrieval in the prototype;
  it does not replace authenticated access control.
- Deleting a document removes its ChromaDB chunks and stored file. Deleting an
  image removes its stored file and catalog entry.
- Images are not included in document retrieval until a separately reviewed
  OCR or vision feature is implemented.

## Data handling and errors

Uploads are limited to one file per request and 20 MB per file. Documents with
no extractable text are rejected; scanned-PDF OCR is not provided. The API
returns `422` for invalid uploads/requests, `404` for a source not owned by the
session, and `503` for local processing or provider errors.

Document text is embedded locally before indexing. Chat sends the question to
OpenAI for scope classification; in-scope questions with evidence also send
the question and retrieved passages for answer generation. Existing `store=False`
settings do not substitute for provider and organizational approval. Never
submit real patient data or other sensitive material without explicit
authorization and governance review.

Run API and frontend tests with:

```powershell
uv run python -m unittest discover -s tests -v
```

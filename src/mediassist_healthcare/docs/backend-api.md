# MediAssist FastAPI Backend

## Purpose and scope

Phases 12–13 expose the Streamlit workflows through a local FastAPI service.
Phases 14–16, 19, and 20 add a LangGraph workflow for planning, account-scoped
document retrieval, optional image analysis, and evidence-based reasoning.
The UI and backend run as separate processes; the Streamlit server
calls the API server over HTTP. Local SQLite-backed accounts authenticate
users and bind each user's uploads to their account.

The implementation is a local learning prototype, not a production healthcare
service. It does not provide roles, fine-grained permissions, rate limiting,
audit logging, or production PHI controls. Password-based login and account
ownership checks are implemented for the prototype, but they are not a
substitute for a production identity provider or security review. Use only
authorized, non-sensitive sample data.

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

Signup and login are public. Every other endpoint except `/api/health` requires
an `Authorization: Bearer <access_token>` header. The `session_id` path
parameter on upload, source, search, and chat routes must match the signed-in
account's ID; a user cannot access another account's sources by changing the
path. Each multipart upload contains one `file` field.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/health` | Check API process health without loading AI models. |
| `POST` | `/api/auth/signup` | Create an account; sign in separately to receive a bearer token. |
| `POST` | `/api/auth/login` | Authenticate with username and password. |
| `GET` | `/api/auth/me` | Return the signed-in user's profile. |
| `POST` | `/api/auth/logout` | Revoke the current bearer session. |
| `POST` | `/api/sessions/{session_id}/documents` | Accept one PDF, DOCX, or TXT file; extract text, chunk, embed locally, and index in ChromaDB. |
| `POST` | `/api/sessions/{session_id}/images` | Store one PNG, JPG, JPEG, or WEBP file for source management. |
| `GET` | `/api/sessions/{session_id}/sources` | List the documents and images uploaded in that session. |
| `DELETE` | `/api/sessions/{session_id}/sources/{file_id}` | Remove the selected file and, for documents, its session-owned ChromaDB chunks. |
| `POST` | `/api/sessions/{session_id}/search` | Retrieve up to 100 chunks using `semantic`, `lexical`, or `hybrid` mode. |
| `POST` | `/api/sessions/{session_id}/chat` | Run the agent workflow with optional stored image IDs and conversation history. |
| `POST` | `/api/sessions/{session_id}/chat/with-images` | Run the same workflow with new multipart image attachments and optional stored image IDs. |

Signup accepts `first_name`, `last_name`, `username`, `password`, and
`confirm_password`. Signup creates the account but does not sign the user in;
the login endpoint must be used separately to obtain a bearer token. Names
must contain 1–80 characters after trimming.
Usernames are case-insensitive, 3–32 characters, and may contain letters,
numbers, periods, underscores, and hyphens. Passwords must contain 8–128
characters, start with an uppercase letter, and include at least one lowercase
letter and one number; special characters are allowed. For example,
`Snooker@147` meets the password format. Signup returns the user's public
profile only. A successful login returns an `access_token`, its `expires_at`
timestamp, and the user's public profile. Tokens expire after
30 minutes; logout revokes the token immediately. The raw password and token are
not stored in the account database.

Example signup request:

```json
{
  "first_name": "Avery",
  "last_name": "Taylor",
  "username": "avery.taylor",
  "password": "Snooker@147",
  "confirm_password": "Snooker@147"
}
```

Use the returned access token as a bearer token for protected endpoints.

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
  "top_k": 5,
  "image_source_ids": [],
  "history": [],
  "external_image_approved": false
}
```

Both chat routes accept up to five complete history turns and up to five images
in total across stored `image_source_ids` and new `image_files`. The
`/chat/with-images` route accepts multipart fields `question`, `mode`, `top_k`,
`image_source_ids` (JSON string array), `history` (JSON object array),
`external_image_approved`, and repeated `image_files` fields. The standard
`/chat` route accepts the JSON request shown above.

Both chat routes validate `top_k` in the range 1–100. The response includes a
status (`answered`, `partial`, `out_of_scope`, or `insufficient_evidence`),
source citations (`[D1]` for documents, `[I1]` for images, and `[M1]` for
read-only MCP results), planned task outcomes, and the retrieval mode and model.
MCP results are available only from fixed read-only tools over the synthetic
`mediassist_demo` dataset. Patient-specific queries require an exact synthetic
patient ID in `SYN-P-####` format. Server filesystem paths, database
credentials, and internal session metadata are not returned.

After reasoning, a separate output-guardrail stage checks answer length,
citation syntax/provenance, completion consistency, and a limited set of
unsafe-treatment patterns. Rejected answers are replaced with a safe refusal.
If a document or image task is incomplete specifically because its source
returned no evidence, the workflow sends targeted feedback to that source
agent and retries evidence collection and reasoning once. Safety rejections,
provider errors, unsupported MCP requests, and evidence-present but uncited
tasks are not retried.

## Storage and deletion

- Uploaded files are stored under the Git-ignored `output/mediassist_api/uploads`
  directory, partitioned by session and generated file ID.
- A local SQLite database records account/session data and source names/upload
  details so the UI can restore its source lists after a rerun.
- Document chunks are indexed in the existing local ChromaDB collection with
  `session_id`, `upload_id`, and original filename metadata.
- Every API search and chat retrieval applies the authenticated account ID as
  a metadata filter, and source routes verify ownership before access.
- Deleting a document removes its ChromaDB chunks and stored file. Deleting an
  image removes its stored file and catalog entry.
- Stored images can be selected for a chat. New chat attachments are validated,
  processed in memory, and not saved as account sources.
- Image analysis is performed by the external vision provider only when both
  the backend operator enables it and the user confirms approval. Otherwise
  image questions are rejected before the provider call.

## Data handling and errors

Uploads are limited to one file per request and 10 MB (10,000,000 bytes) per
file. Documents with
no extractable text are rejected; scanned-PDF OCR is not provided. The API
returns `422` for invalid uploads/requests, `404` for a source not owned by the
session, and `503` for local processing or provider errors. Unexpected
unhandled server errors return a generic `500` message with a request ID;
internal exception text is not included in the response.

Document text is embedded locally before indexing. Chat uses the configured
OpenAI model for planning and reasoning; bounded history and retrieved evidence
may also be included in these prompts. Common identifiers are masked on a best
effort basis, which is not certified de-identification. Raw image bytes are not
redacted. Image analysis is disabled by default; configure
`OPENAI_VISION_MODEL` and set `MEDIASSIST_ALLOW_EXTERNAL_VISION=true` only after
provider and organizational review. The user must also approve external image
processing for each request. Provider `store=False` settings do not substitute
for governance approval. Never submit real patient data or other sensitive
material without explicit authorization.

See the [guardrails and governance guide](guardrails-and-governance.md) for
agent behavior, input/output controls, and residual prototype risks. The
workflow is orchestrated with LangGraph. Phase 18 MCP access is limited to the
synthetic dataset and the configured database account's permissions.

## Observability and privacy

API responses include an `X-Request-ID` for support correlation and baseline
security headers. Structured application events include only allowlisted
operational metadata such as route templates, HTTP status, duration, workflow
node names, aggregate counts, and exception class/provider codes. Request
bodies, account/session IDs, filenames, prompts, answers, retrieved text,
image bytes, and exception messages are excluded. Uvicorn access logging is
disabled so dynamic URLs are not written to its default access log.

Optional LangSmith tracing is disabled by default. To enable it on the backend,
set `MEDIASSIST_ENABLE_LANGSMITH=true`, provide `LANGSMITH_API_KEY`, and
optionally set `LANGSMITH_PROJECT`. The observer sends workflow/node labels
and aggregate metadata only; ambient LangChain/LangGraph tracing is disabled
for this workflow. Review the [governance guide](guardrails-and-governance.md)
before enabling external telemetry. Local log retention and access controls
depend on the configured Python logging destination and deployment operator.

## Session analytics dashboard (Phase 22)

The Streamlit **Analytics dashboard** summarizes activity in the current
signed-in UI session. It displays workflow outcome counts, median response
time, task completion, citation/source-type counts, average node timings, and
content-free execution traces. It retains at most 200 recent runs in
`st.session_state` and clears them on logout or when the Streamlit session ends.
It does not use a server-side database or retain prompts, answers, document
passages, image bytes, or model payloads. Failed requests are represented only
by their status and end-to-end request duration; internal error details remain
in the chat error message, not in analytics records.

Run API and frontend tests with:

```powershell
uv run python -m unittest discover -s tests -v
```

# MediAssist AI Guardrails and Governance

## 1. Purpose and operating boundary

This guide documents the guardrails implemented for the planner,
retriever, multimodal, and reasoning workflow (Phases 14–16 and 19), the
prototype-scoped security controls for Phase 24, and privacy-minimized
observability for Phase 25. It is an engineering and governance aid for an
educational prototype, not a compliance certification, clinical safety case,
or authorization to process real patient information.

Use only authorized, non-sensitive test data. MediAssist does not diagnose,
recommend treatment, or replace a qualified healthcare professional. Do not
rely on its output for clinical or operational decisions without independent
review and verification against approved source material.

The implementation does not provide production-grade PHI de-identification,
role-based authorization, comprehensive audit logging, clinical validation,
or an incident-response system. It is not represented as HIPAA-compliant or
production-ready.

## 2. Data flow and external processing

| Input or evidence | Processing | External-provider behavior |
|---|---|---|
| Current question | Length check, prompt-override pattern check, and best-effort masking of common identifiers | Sent to the configured OpenAI chat model for planning and, when needed, reasoning |
| Recent conversation | Limited to five question/answer pairs and best-effort masking before model prompts | May be sent to the configured OpenAI chat model |
| Retrieved documents | Retrieved with the authenticated account ID as the session metadata filter; common identifiers are best-effort masked before reasoning | Relevant evidence may be sent to the configured OpenAI chat model |
| Stored or newly attached images | Validated for supported image type, size, and per-question count; selected stored files must belong to the authenticated account | Raw image bytes are sent to the vision provider only when the server and user both approve |
| Provider output | Parsed against structured response shapes; citations and task outcomes are checked before returning | Not independently verified for factual or clinical correctness |

The image-analysis control is deliberately two-part:

1. The backend operator must set `MEDIASSIST_ALLOW_EXTERNAL_VISION=true`.
   The default is disabled.
2. The user must confirm in the UI that external processing of the selected
   images is approved for the request.

If either check is absent, the image workflow stops before sending image bytes
to the vision provider. This setting is an application control, not a substitute
for vendor review, contractual controls, data minimization, or organizational
approval. Configure `OPENAI_VISION_MODEL` only after the provider and model have
been reviewed for the intended data and use.

The current image pipeline requests transcription and visible-image
description. It is not a local OCR solution and does not establish that an
image is authentic, complete, legible, or clinically interpreted correctly.
Direct chat attachments are processed in memory and are not persisted as
sources. Previously uploaded images remain stored until deleted through the
source-management flow.

## 3. Implemented input controls

| Control | Current behavior | Important limitation |
|---|---|---|
| Question size | Empty questions are rejected; questions are limited to 4,000 characters | Size limits do not establish that content is safe or appropriate |
| Conversation context | At most five complete turns are considered | History can still contain sensitive or misleading content |
| Image count | At most five images per question, combining stored and new images | The limit is not a content or privacy review |
| Upload size | Uploaded documents and images are limited to 10 MB per file | File-type and signature checks do not prove a file is harmless |
| Prompt override | A small set of common instruction-override phrases is rejected before planning | Pattern detection is not comprehensive prompt-injection protection |
| Identifier masking | Common labelled IDs, SSNs, emails, phone numbers, dates of birth, and labelled names are best-effort masked in text sent to model prompts | This is not certified de-identification; unlabelled, novel, contextual, or embedded identifiers may remain |
| Account scope | Stored image selection and document retrieval are restricted to the authenticated account/session | The prototype lacks production tenant isolation and fine-grained authorization |

Treat user inputs, uploaded documents, retrieved passages, image text, and
conversation history as untrusted data. Do not treat instructions found inside
them as system instructions. Pattern checks reduce a narrow set of obvious
override attempts but do not prevent indirect prompt injection or malicious
content embedded in a document or image.

Images are not redacted before external vision processing. Obtain explicit
organizational approval and user authorization before enabling this feature;
otherwise keep the backend setting disabled and do not upload sensitive images.

## 4. Implemented output controls

- Planner responses must parse as structured data and use supported task
  sources (`documents`, `images`, or `mcp`). Plans are bounded to six tasks.
- The reasoning component is given planned tasks and source-labelled evidence.
  The separate output guardrail checks that answer citations exactly match
  those declared in the result and that each citation's source label, source
  type, and chunk number match evidence supplied to the workflow.
- A task is marked complete only when the response reports completion and the
  task has supporting evidence with a matching citation. Missing evidence,
  unsupported tasks, and MCP requests are reported as incomplete.
- MCP tasks remain incomplete because Phase 18 is not implemented. The
  application does not connect directly to PostgreSQL.
- A distinct output-guardrail graph node runs after reasoning. It checks
  response length, citation syntax and provenance, completion consistency,
  and a limited set of direct treatment-advice patterns. A rejected candidate
  is replaced with a fixed refusal and marked `insufficient_evidence`; it is
  not sent back through reasoning or evidence recovery.
- Chat results expose `answered`, `partial`, `out_of_scope`, or
  `insufficient_evidence` status and per-task completion reasons so that
  missing information is visible to the user.

When reasoning returns incomplete tasks because their assigned document or
image source produced no evidence, the workflow may perform **one bounded
evidence-recovery pass**. It sends task-specific feedback to document retrieval
or image analysis, then asks reasoning to evaluate the refreshed evidence.
Tasks with evidence but no citation, unsupported MCP tasks, safety-rejected
answers, and planner/retrieval/provider exceptions do not trigger recovery.
If the retry still cannot complete a task, the final partial or
`insufficient_evidence` result is returned. The retry count is capped at one.

These are structural and pattern-based checks, not clinical validation. A
citation proves only that a reference was supplied; it does not prove that the
source supports every statement. The output pattern checks are not
comprehensive and may miss unsafe advice or reject benign language. Human
review remains necessary.

## 5. Security and observability implementation (Phases 24–25)

The current security controls include authenticated account ownership checks
for private API workflows, 30-minute bearer sessions with logout revocation,
bounded request and upload sizes, supported-type and signature validation,
best-effort text masking, prompt-override checks, answer/citation validation,
and two-part approval for external image processing. The API also returns
request IDs and baseline security headers. These controls reduce specific
risks but do not replace a security assessment, production identity service,
rate limiting, secure deployment configuration, or comprehensive audit
controls.

Application events are emitted as structured JSON through the
`mediassist_healthcare.observability` logger. The event schema allows only
fixed event and workflow labels, route templates, HTTP methods/status codes,
request/trace IDs, durations, bounded counts, and exception class/provider
status/code. Exception messages and tracebacks are not logged by these
application paths. Uvicorn access logging is disabled to avoid logging URLs
that contain account/session identifiers. Unexpected API exceptions return a
generic 500 response with a request ID; the server-side event contains safe
diagnostic metadata only.

LangSmith tracing is **off by default**. To enable it, configure the following
on the backend only:

```dotenv
MEDIASSIST_ENABLE_LANGSMITH=true
LANGSMITH_API_KEY=your-langsmith-api-key
LANGSMITH_PROJECT=mediassist-healthcare
```

The observer uses explicit LangSmith run trees with a fixed workflow name,
node labels, aggregate counts, durations, retrieval mode, and image count.
Question text, answers, conversation history, retrieved passages, image bytes,
account/session IDs, filenames, and filesystem paths are not included. The
LangSmith client also hides run inputs and outputs as a defense in depth. The
workflow disables ambient LangChain/LangGraph tracing so environment-level
tracing cannot export graph state. Telemetry failures are reported using safe
exception metadata and do not fail the chat workflow.

Enabling LangSmith sends the listed operational metadata to the configured
LangSmith service. Operators remain responsible for reviewing the service,
credentials, access, retention, and organizational approval. Local structured
logs are written to the configured Python logging destination; durable
retention, access controls, alerting, and audit review must be configured by
the deployment operator.

## 6. Governance responsibilities

| Role | Minimum responsibility before a deployment or data change |
|---|---|
| Product owner / clinical sponsor | Define intended use, prohibited uses, user population, escalation paths, and whether the feature is appropriate for the workflow |
| Privacy and security reviewers | Approve data categories, retention, access controls, provider processing, threat assessment, and incident procedures |
| Data owner | Confirm rights to use each dataset, document provenance, and approve access and retention |
| Backend operator | Keep external vision disabled unless approved; protect credentials; maintain dependencies and storage; review errors and operational health |
| Application owner | Maintain tests, model/provider configuration, source-grounding behavior, user-facing disclosures, and documented limitations |
| End user / reviewer | Use only authorized data, verify citations and source documents, and escalate uncertain or consequential results to a qualified person |

Approval should be recorded outside the application. This prototype does not
implement approval records, user roles, audit trails, or per-dataset policy
enforcement.

## 7. Recommended operational controls before production

Before any real deployment, complete and independently review at least:

1. A documented intended-use and prohibited-use assessment, including clinical
   safety and human-oversight requirements.
2. Privacy, security, and legal review of data flows, provider terms, model
   retention, data residency, subprocessors, and contractual safeguards.
3. A threat model for authentication, tenant boundaries, prompt injection,
   uploaded files, model/provider failures, and misuse.
4. Production identity, role-based and document-level access controls,
   encryption, key management, secure transport, rate limits, and audit trails.
5. Retention and deletion policies for uploads, extracted text, vector records,
   backups, logs, and provider-side data.
6. A reviewed incident-response and breach-notification process, including
   accountable owners and tested escalation routes.
7. Representative evaluation of retrieval quality, citation correctness,
   abstention, bias, privacy leakage, unsafe output, latency, and failure
   handling, with documented release criteria.
8. Monitoring for provider availability, errors, unexpected data flows,
   changes in model behavior, and configuration drift.
9. Accessible user disclosures, training, feedback, and a process for
   correcting or reporting harmful or inaccurate outputs.
10. A formal approval gate before enabling external vision or processing any
    sensitive information.

## 8. Known implementation boundaries

- The workflow uses a small LangGraph state graph. LangGraph orchestrates the
  nodes; it does not add persistence or distributed execution. The local
  structured events and optional metadata-only LangSmith observer are not a
  production monitoring or audit platform.
- Phase 22 dashboard telemetry is limited to the current signed-in Streamlit
  session, capped at 200 runs, and cleared on logout/session end. It excludes
  question and response text, uploaded content, and model payloads.
- MCP integration (Phase 18) is not implemented; such tasks are explicitly
  incomplete.
- The image model is an external provider; local OCR/vision is not configured.
- Identifier masking is best effort and raw image content is not masked.
- The application has no production roles, comprehensive audit trail, incident
  management, or certified de-identification process.
- The reasoning and output checks cannot guarantee factual accuracy, source
  entailment, clinical safety, or absence of prompt injection.
- OpenAI API requests use `store=False` where configured, but this does not
  establish zero retention or eliminate the need for provider and governance
  review.

## 9. Configuration reference

```dotenv
OPENAI_KEY=your-openai-api-key
OPENAI_CHAT_MODEL=gpt-4o-mini
OPENAI_VISION_MODEL=gpt-4o-mini
MEDIASSIST_ALLOW_EXTERNAL_VISION=false
MEDIASSIST_ENABLE_LANGSMITH=false
LANGSMITH_PROJECT=mediassist-healthcare
```

Keep credentials in the ignored local `.env` file or an approved secret
manager. Do not place real credentials in this document, source code, issue
reports, or test fixtures.

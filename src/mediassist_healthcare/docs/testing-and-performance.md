# Testing and performance baselines

## Phase 26: unit testing

Run the unit and UI tests from the repository root:

```powershell
uv run python -m unittest discover -s tests -v
```

The suite covers dashboard aggregation, privacy-safe telemetry, agent behavior,
document ingestion, and read-only MCP safeguards. The Streamlit `AppTest` checks
that the authenticated analytics page renders its metrics and charts.

## Phase 27: integration testing

The API tests use temporary storage and synthetic inputs. They exercise account
authentication, document upload/indexing, session-scoped retrieval, agent
orchestration with deterministic model responses, grounded citations, and the
dashboard-safe analytics record. No live model provider or Aiven service is
required by the test suite.

The prescription scenario uses a fictional text document. It does not represent
OCR or scanned-PDF processing; image analysis remains a separate capability
that requires explicit external-processing approval.

## Phase 28: performance testing

Run the bounded, sequential local baseline:

```powershell
uv run python -m mediassist_healthcare.performance_benchmark --iterations 10
```

The report includes p50, p95, and measured throughput for synthetic text
extraction/chunking, the local SQLite source-catalog query, and aggregation of
the dashboard's maximum 200 safe workflow records. It makes no service-level
objective or production-capacity claim. Results depend on the machine, Python
environment, storage, and current system load.

To additionally measure a fixed PostgreSQL query against the synthetic Aiven
dataset, opt in explicitly:

```powershell
uv run python -m mediassist_healthcare.performance_benchmark --iterations 10 --aiven
```

This option uses the existing allowlisted patient-count `SELECT` through the
read-only MCP server. Configure its database environment variables with a
dedicated `SELECT`-only account first. It is sequential and capped at 50
queries; it performs no writes and returns no patient-level records. Do not use
administrator credentials or production patient data. The local run never
connects to Aiven.

These are baselines, not a concurrent load test. Full workflow latency,
embedding-model throughput, large-corpus retrieval quality, and production
capacity still require a separately approved representative environment and
explicit performance targets.

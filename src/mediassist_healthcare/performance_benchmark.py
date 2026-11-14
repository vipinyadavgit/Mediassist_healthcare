"""Run bounded, repeatable performance baselines on synthetic MediAssist data."""

from __future__ import annotations

import argparse
import json
import math
import tempfile
import time
from pathlib import Path
from typing import Callable

from mediassist_healthcare.backend import SourceCatalog, SourceRecord
from mediassist_healthcare.frontend import build_dashboard_metrics
from mediassist_healthcare.ingestion import load_document
from mediassist_healthcare.text_processing import chunk_by_paragraph


def _percentile(samples: list[float], percentile: float) -> float:
    ordered = sorted(samples)
    rank = max(1, math.ceil(percentile * len(ordered)))
    return ordered[rank - 1]


def _measure(
    name: str,
    operation: Callable[[], object],
    iterations: int,
) -> dict[str, float | int | str]:
    samples: list[float] = []
    for _ in range(iterations):
        started = time.perf_counter()
        operation()
        samples.append(time.perf_counter() - started)
    total_seconds = sum(samples)
    return {
        "operation": name,
        "iterations": iterations,
        "p50_ms": round(_percentile(samples, 0.50) * 1000, 3),
        "p95_ms": round(_percentile(samples, 0.95) * 1000, 3),
        "throughput_per_second": (
            round(iterations / total_seconds, 3) if total_seconds else 0.0
        ),
    }


def _make_dashboard_runs() -> list[dict[str, object]]:
    return [
        {
            "status": "answered" if index % 4 else "partial",
            "duration_ms": 250 + index,
            "citations": [{"source_type": "documents"}],
            "tasks": [{"source": "documents", "status": "completed"}],
            "traces": [{"node": "Retriever", "duration_ms": 12}],
        }
        for index in range(200)
    ]


def run_benchmarks(iterations: int, include_aiven: bool) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="mediassist-benchmark-") as directory:
        root = Path(directory)
        document_path = root / "synthetic-document.txt"
        document_path.write_text(
            "\n\n".join(
                f"Synthetic training section {index}: sample policy content for "
                "offline ingestion benchmarking."
                for index in range(200)
            ),
            encoding="utf-8",
        )
        session_id = "00000000-0000-4000-8000-000000000001"
        catalog = SourceCatalog(root / "catalog.sqlite3")
        for index in range(25):
            file_id = f"00000000-0000-4000-8000-{index + 1:012d}"
            catalog.add(
                SourceRecord(
                    file_id=file_id,
                    session_id=session_id,
                    name=f"synthetic-{index}.txt",
                    kind="document",
                    size_bytes=128,
                    storage_path=str(root / f"synthetic-{index}.txt"),
                    indexed_chunks=1,
                    created_at="2026-01-01T00:00:00+00:00",
                )
            )

        dashboard_runs = _make_dashboard_runs()
        measurements = [
            _measure(
                "synthetic text extraction and chunking",
                lambda: chunk_by_paragraph(
                    load_document(document_path).text,
                    max_chars=1000,
                ),
                iterations,
            ),
            _measure(
                "local source catalog query",
                lambda: catalog.list_for_session(session_id),
                iterations,
            ),
            _measure(
                "dashboard aggregation of 200 safe session records",
                lambda: build_dashboard_metrics(dashboard_runs),
                iterations,
            ),
        ]

        if include_aiven:
            from mediassist_healthcare.mcp_server import count_demo_records

            measurements.append(
                _measure(
                    "Aiven fixed read-only synthetic patient count",
                    lambda: count_demo_records("patients"),
                    iterations,
                )
            )

    return {
        "note": (
            "Sequential local baselines; no AI provider calls, concurrent load, "
            "or service-level targets are included."
        ),
        "measurements": measurements,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--iterations",
        type=int,
        default=10,
        help="Sequential samples per operation (1-50; default: 10).",
    )
    parser.add_argument(
        "--aiven",
        action="store_true",
        help=(
            "Also time the fixed read-only synthetic patient count query; requires "
            "the dedicated read-only database environment variables."
        ),
    )
    arguments = parser.parse_args()
    if not 1 <= arguments.iterations <= 50:
        parser.error("--iterations must be between 1 and 50.")
    print(
        json.dumps(
            run_benchmarks(arguments.iterations, arguments.aiven),
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

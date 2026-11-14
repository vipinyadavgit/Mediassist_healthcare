"""Retrieve allowlisted structured records through the local MCP server."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass
from typing import Any

from mcp import Client, StdioServerParameters
from mcp.shared.exceptions import MCPError
from mcp.types import TextContent

from mediassist_healthcare.agent_models import PlannedTask, SourceEvidence
from mediassist_healthcare.settings import (
    PROJECT_ROOT,
    get_mcp_database_environment,
)

_PATIENT_ID = re.compile(r"\bSYN-P-\d{4}\b", re.IGNORECASE)
_COUNT_REQUEST = re.compile(r"\b(how many|count|number of|total)\b", re.IGNORECASE)
_COUNT_TABLES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("patients", ("patient", "patients")),
    ("departments", ("department", "departments")),
    ("providers", ("provider", "providers")),
    ("patient_insurance", ("insurance enrollment", "insurance record")),
    ("appointments", ("appointment", "appointments")),
    ("encounters", ("encounter", "encounters", "visit", "visits")),
    ("admissions", ("admission", "admissions")),
    ("diagnoses", ("diagnosis", "diagnoses")),
    ("lab_results", ("lab", "laboratory", "test result", "test results")),
    ("medication_orders", ("medication", "medications", "prescription")),
    ("insurance_claims", ("claim", "claims")),
    ("invoices", ("invoice", "invoices", "billing record", "billing records")),
    ("payments", ("payment", "payments")),
)
_CATEGORY_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("lab_results", ("lab", "laboratory", "test result", "test results")),
    ("medications", ("medication", "medications", "prescription")),
    ("appointments", ("appointment", "appointments")),
    ("admissions", ("admission", "admissions")),
    ("diagnoses", ("diagnosis", "diagnoses")),
    (
        "billing",
        ("claim", "claims", "invoice", "invoices", "payment", "bill", "billing"),
    ),
    ("insurance", ("insurance", "coverage", "payer")),
    ("encounters", ("encounter", "encounters", "visit", "visits", "history")),
)
_SOURCE_LABELS = {
    "appointments": "Aiven synthetic appointments",
    "encounters": "Aiven synthetic encounters",
    "admissions": "Aiven synthetic admissions",
    "diagnoses": "Aiven synthetic diagnoses",
    "lab_results": "Aiven synthetic lab results",
    "medications": "Aiven synthetic medication orders",
    "insurance": "Aiven synthetic insurance records",
    "billing": "Aiven synthetic billing records",
    "overview": "Aiven synthetic patient overview",
}


@dataclass(frozen=True)
class MCPRetrievalResult:
    """Return structured evidence and explicit reasons for skipped MCP tasks."""

    evidence: tuple[SourceEvidence, ...]
    unavailable_reasons: dict[str, str]


@dataclass(frozen=True)
class _ToolRequest:
    """Describe one fixed MCP tool call selected from a planned task."""

    task: PlannedTask
    name: str
    arguments: dict[str, object]
    source_label: str


class MCPDataAgent:
    """Select only predefined read-only MCP tools for planned structured-data tasks."""

    def retrieve(
        self,
        tasks: tuple[PlannedTask, ...],
        question: str,
    ) -> MCPRetrievalResult:
        """Call bounded MCP tools and return citation-ready structured evidence."""
        requests: list[_ToolRequest] = []
        unavailable_reasons: dict[str, str] = {}
        for task in tasks:
            request, reason = self._build_request(task, question)
            if request is None:
                unavailable_reasons[task.task_id] = reason
            else:
                requests.append(request)
        if not requests:
            return MCPRetrievalResult((), unavailable_reasons)

        database_environment = get_mcp_database_environment()
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mediassist_healthcare.mcp_server"],
            env=self._server_environment(database_environment),
            cwd=PROJECT_ROOT,
        )
        try:
            results = asyncio.run(self._call_tools(server, requests))
        except (MCPError, OSError, TimeoutError) as error:
            raise RuntimeError(
                "The local read-only MCP database service could not be reached."
            ) from error
        evidence = tuple(
            SourceEvidence(
                reference=f"M{index}",
                task_id=request.task.task_id,
                source_type="mcp",
                source=request.source_label,
                text=json.dumps(payload, ensure_ascii=True, default=str),
                chunk_number=1,
            )
            for index, (request, payload) in enumerate(
                zip(requests, results, strict=True),
                start=1,
            )
        )
        return MCPRetrievalResult(evidence, unavailable_reasons)

    @staticmethod
    def _build_request(
        task: PlannedTask,
        question: str,
    ) -> tuple[_ToolRequest | None, str]:
        description = task.description.casefold()
        question_text = question.casefold()
        task_text = description if description.strip() else question_text
        if _COUNT_REQUEST.search(question_text) or _COUNT_REQUEST.search(task_text):
            patient_id = (
                _PATIENT_ID.search(task.description)
                or _PATIENT_ID.search(question)
            )
            if patient_id is not None:
                return None, (
                    "Patient-specific record counts are not supported; request "
                    "the bounded records for that synthetic patient instead."
                )
            table_name = MCPDataAgent._count_table(task_text)
            if table_name is None:
                table_name = MCPDataAgent._count_table(question_text)
            if table_name is None:
                return None, (
                    "Specify one supported synthetic demo table to count."
                )
            return (
                _ToolRequest(
                    task,
                    "count_demo_records",
                    {"table_name": table_name},
                    f"Aiven synthetic {table_name}",
                ),
                "",
            )

        patient_id = (
            _PATIENT_ID.search(task.description)
            or _PATIENT_ID.search(question)
        )
        if patient_id is None:
            return None, (
                "Provide an exact synthetic patient ID in SYN-P-#### format "
                "to retrieve patient-specific records."
            )
        synthetic_patient_id = patient_id.group(0).upper()
        category = MCPDataAgent._record_category(description)
        if category is None:
            category = MCPDataAgent._record_category(question_text)
        if category is None:
            return (
                _ToolRequest(
                    task,
                    "get_patient_overview",
                    {"synthetic_patient_id": synthetic_patient_id},
                    _SOURCE_LABELS["overview"],
                ),
                "",
            )
        return (
            _ToolRequest(
                task,
                "get_patient_records",
                {
                    "synthetic_patient_id": synthetic_patient_id,
                    "category": category,
                    "limit": 25,
                },
                _SOURCE_LABELS[category],
            ),
            "",
        )

    @staticmethod
    def _count_table(text: str) -> str | None:
        matching_tables = {
            table_name
            for table_name, terms in _COUNT_TABLES
            if any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms)
        }
        return next(iter(matching_tables)) if len(matching_tables) == 1 else None

    @staticmethod
    def _record_category(text: str) -> str | None:
        for category, terms in _CATEGORY_TERMS:
            if any(re.search(rf"\b{re.escape(term)}\b", text) for term in terms):
                return category
        return None

    @staticmethod
    def _server_environment(database_environment: dict[str, str]) -> dict[str, str]:
        environment = dict(database_environment)
        for name in (
            "PATH",
            "SYSTEMROOT",
            "WINDIR",
            "TEMP",
            "TMP",
            "USERPROFILE",
        ):
            value = os.environ.get(name)
            if value:
                environment[name] = value
        return environment

    @staticmethod
    async def _call_tools(
        server: StdioServerParameters,
        requests: list[_ToolRequest],
    ) -> list[dict[str, Any]]:
        async with Client(server) as client:
            payloads: list[dict[str, Any]] = []
            for request in requests:
                result = await client.call_tool(request.name, request.arguments)
                if result.is_error:
                    raise RuntimeError(
                        "A read-only MCP database tool failed. Check the "
                        "backend's database configuration and connection."
                    )
                text_blocks = [
                    block.text
                    for block in result.content
                    if isinstance(block, TextContent)
                ]
                if len(text_blocks) != 1:
                    raise RuntimeError(
                        "The MCP database tool returned an invalid response."
                    )
                try:
                    payload = json.loads(text_blocks[0])
                except json.JSONDecodeError as error:
                    raise RuntimeError(
                        "The MCP database tool returned invalid structured data."
                    ) from error
                if not isinstance(payload, dict):
                    raise RuntimeError(
                        "The MCP database tool returned an invalid response."
                    )
                payloads.append(payload)
            return payloads

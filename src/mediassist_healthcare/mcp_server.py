"""Expose a small, read-only MCP interface to the synthetic PostgreSQL dataset."""

from __future__ import annotations

import json
import re
from typing import Literal

import psycopg
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from psycopg.rows import dict_row

from mediassist_healthcare.settings import (
    DatabaseConfigurationError,
    get_mcp_database_environment,
)

READ_ONLY_TOOL = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

RECORD_QUERIES: dict[str, str] = {
    "appointments": """
        SELECT a.synthetic_appointment_id, a.scheduled_at, a.status, a.reason,
               a.location, p.display_name AS provider, d.department_name
        FROM mediassist_demo.appointments AS a
        JOIN mediassist_demo.patients AS patient ON patient.patient_id = a.patient_id
        JOIN mediassist_demo.providers AS p ON p.provider_id = a.provider_id
        JOIN mediassist_demo.departments AS d ON d.department_id = a.department_id
        WHERE patient.synthetic_patient_id = %s
        ORDER BY a.scheduled_at DESC
        LIMIT %s
    """,
    "encounters": """
        SELECT e.synthetic_encounter_id, e.encounter_at, e.encounter_type,
               e.chief_complaint, e.summary
        FROM mediassist_demo.encounters AS e
        JOIN mediassist_demo.patients AS patient ON patient.patient_id = e.patient_id
        WHERE patient.synthetic_patient_id = %s
        ORDER BY e.encounter_at DESC
        LIMIT %s
    """,
    "admissions": """
        SELECT a.synthetic_admission_id, a.admitted_on, a.discharged_on,
               a.status, a.admission_type, a.ward, a.room
        FROM mediassist_demo.admissions AS a
        JOIN mediassist_demo.patients AS patient ON patient.patient_id = a.patient_id
        WHERE patient.synthetic_patient_id = %s
        ORDER BY a.admitted_on DESC
        LIMIT %s
    """,
    "diagnoses": """
        SELECT d.diagnosis_code, d.diagnosis_name, d.category, d.is_primary,
               d.recorded_on
        FROM mediassist_demo.diagnoses AS d
        JOIN mediassist_demo.patients AS patient ON patient.patient_id = d.patient_id
        WHERE patient.synthetic_patient_id = %s
        ORDER BY d.recorded_on DESC
        LIMIT %s
    """,
    "lab_results": """
        SELECT l.synthetic_order_id, l.test_name, l.result_value, l.unit,
               l.reference_low, l.reference_high, l.flag, l.collected_at, l.status
        FROM mediassist_demo.lab_results AS l
        JOIN mediassist_demo.patients AS patient ON patient.patient_id = l.patient_id
        WHERE patient.synthetic_patient_id = %s
        ORDER BY l.collected_at DESC
        LIMIT %s
    """,
    "medications": """
        SELECT m.synthetic_order_id, m.medication_name, m.dose, m.route,
               m.frequency, m.start_date, m.end_date, m.status, m.notes
        FROM mediassist_demo.medication_orders AS m
        JOIN mediassist_demo.patients AS patient ON patient.patient_id = m.patient_id
        WHERE patient.synthetic_patient_id = %s
        ORDER BY m.start_date DESC
        LIMIT %s
    """,
    "insurance": """
        SELECT i.synthetic_member_id, i.payer_name, i.plan_name,
               i.effective_from, i.effective_to, i.status
        FROM mediassist_demo.patient_insurance AS i
        JOIN mediassist_demo.patients AS patient ON patient.patient_id = i.patient_id
        WHERE patient.synthetic_patient_id = %s
        ORDER BY i.effective_from DESC
        LIMIT %s
    """,
    "billing": """
        SELECT c.synthetic_claim_id, c.submitted_on, c.status AS claim_status,
               c.billed_amount, c.approved_amount, c.denial_reason,
               i.synthetic_invoice_id, i.issued_on, i.due_on,
               i.total_amount, i.status AS invoice_status,
               COALESCE(SUM(payment.amount), 0) AS paid_amount
        FROM mediassist_demo.insurance_claims AS c
        JOIN mediassist_demo.patients AS patient ON patient.patient_id = c.patient_id
        LEFT JOIN mediassist_demo.invoices AS i ON i.claim_id = c.claim_id
        LEFT JOIN mediassist_demo.payments AS payment ON payment.invoice_id = i.invoice_id
        WHERE patient.synthetic_patient_id = %s
        GROUP BY c.claim_id, i.invoice_id
        ORDER BY c.submitted_on DESC
        LIMIT %s
    """,
}

COUNT_QUERIES: dict[str, str] = {
    table: f"SELECT COUNT(*) AS record_count FROM mediassist_demo.{table}"
    for table in (
        "departments",
        "providers",
        "patients",
        "patient_insurance",
        "appointments",
        "encounters",
        "admissions",
        "diagnoses",
        "lab_results",
        "medication_orders",
        "insurance_claims",
        "invoices",
        "payments",
    )
}

PATIENT_OVERVIEW_QUERY = """
    SELECT synthetic_patient_id, first_name, last_name, gender, city
    FROM mediassist_demo.patients
    WHERE synthetic_patient_id = %s
    LIMIT 1
"""
ALLOWED_SELECTS = frozenset(
    (
        PATIENT_OVERVIEW_QUERY,
        *RECORD_QUERIES.values(),
        *COUNT_QUERIES.values(),
    )
)
_PATIENT_ID_PATTERN = re.compile(r"SYN-P-\d{4}", re.IGNORECASE)

mcp = MCPServer(
    "MediAssist read-only database",
    instructions=(
        "These tools are read-only and access only the synthetic "
        "mediassist_demo dataset. They do not accept or execute SQL."
    ),
)


def _run_select(
    query: str,
    parameters: tuple[object, ...] = (),
) -> list[dict[str, object]]:
    """Execute one fixed SELECT inside a read-only PostgreSQL transaction."""
    if query not in ALLOWED_SELECTS:
        raise ValueError("Only predefined read-only queries are allowed.")
    try:
        environment = get_mcp_database_environment()
        connection_settings: dict[str, object] = {
            "host": environment["MEDIASSIST_DB_HOST"],
            "port": int(environment["MEDIASSIST_DB_PORT"]),
            "dbname": environment["MEDIASSIST_DB_NAME"],
            "user": environment["MEDIASSIST_DB_USER"],
            "password": environment["MEDIASSIST_DB_PASSWORD"],
            "sslmode": environment["MEDIASSIST_DB_SSLMODE"],
            "connect_timeout": 10,
            "options": (
                "-c default_transaction_read_only=on "
                "-c search_path=mediassist_demo"
            ),
            "row_factory": dict_row,
        }
        if "MEDIASSIST_DB_SSLROOTCERT" in environment:
            connection_settings["sslrootcert"] = environment[
                "MEDIASSIST_DB_SSLROOTCERT"
            ]
        with psycopg.connect(**connection_settings) as connection:
            connection.execute("SET TRANSACTION READ ONLY")
            return list(connection.execute(query, parameters).fetchall())
    except (psycopg.Error, OSError) as error:
        raise ToolError(
            "The read-only database query failed. Check the backend's database "
            "configuration and connection."
        ) from error
    except DatabaseConfigurationError as error:
        raise ToolError(str(error)) from error


def _json_result(result: dict[str, object]) -> str:
    return json.dumps(result, ensure_ascii=True, default=str)


def _validate_patient_id(synthetic_patient_id: str) -> str:
    if not _PATIENT_ID_PATTERN.fullmatch(synthetic_patient_id):
        raise ToolError("Use an exact synthetic patient ID in SYN-P-#### format.")
    return synthetic_patient_id.upper()


@mcp.tool(
    title="Get synthetic patient overview",
    annotations=READ_ONLY_TOOL,
)
def get_patient_overview(synthetic_patient_id: str) -> str:
    """Read basic demographic fields for an exact synthetic patient ID."""
    patient_id = _validate_patient_id(synthetic_patient_id)
    rows = _run_select(PATIENT_OVERVIEW_QUERY, (patient_id,))
    return _json_result(
        {
            "source_table": "patients",
            "record_count": len(rows),
            "records": rows,
        }
    )


@mcp.tool(
    title="Get synthetic patient records",
    annotations=READ_ONLY_TOOL,
)
def get_patient_records(
    synthetic_patient_id: str,
    category: Literal[
        "appointments",
        "encounters",
        "admissions",
        "diagnoses",
        "lab_results",
        "medications",
        "insurance",
        "billing",
    ],
    limit: int = 10,
) -> str:
    """Read a bounded, allowlisted record category for a synthetic patient."""
    query = RECORD_QUERIES.get(category)
    if query is None:
        raise ToolError("That record category is not supported.")
    if not 1 <= limit <= 25:
        raise ToolError("The record limit must be between 1 and 25.")
    patient_id = _validate_patient_id(synthetic_patient_id)
    rows = _run_select(query, (patient_id, limit))
    return _json_result(
        {
            "source_table": category,
            "record_count": len(rows),
            "records": rows,
        }
    )


@mcp.tool(
    title="Count synthetic demo records",
    annotations=READ_ONLY_TOOL,
)
def count_demo_records(
    table_name: Literal[
        "departments",
        "providers",
        "patients",
        "patient_insurance",
        "appointments",
        "encounters",
        "admissions",
        "diagnoses",
        "lab_results",
        "medication_orders",
        "insurance_claims",
        "invoices",
        "payments",
    ],
) -> str:
    """Return a row count from one allowlisted synthetic demo table."""
    query = COUNT_QUERIES.get(table_name)
    if query is None:
        raise ToolError("That demo table is not supported.")
    rows = _run_select(query)
    return _json_result(
        {
            "table_name": table_name,
            "record_count": rows[0]["record_count"] if rows else 0,
        }
    )


if __name__ == "__main__":
    mcp.run(transport="stdio")

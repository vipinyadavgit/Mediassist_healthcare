"""Verify MCP exposes only bounded, read-only database operations."""

from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

from mcp import Client
from mcp.types import TextContent

from mediassist_healthcare.agent_models import PlannedTask
from mediassist_healthcare.mcp_agent import MCPDataAgent
from mediassist_healthcare import mcp_server


class MCPServerTests(unittest.TestCase):
    """Exercise the actual MCP protocol without connecting to a database."""

    def test_server_exposes_only_read_only_allowlisted_tools(self) -> None:
        async def list_tools() -> list[object]:
            async with Client(mcp_server.mcp) as client:
                return (await client.list_tools()).tools

        tools = asyncio.run(list_tools())

        self.assertEqual(
            {tool.name for tool in tools},
            {
                "get_patient_overview",
                "get_patient_records",
                "count_demo_records",
            },
        )
        self.assertTrue(
            all(
                tool.annotations is not None
                and tool.annotations.read_only_hint is True
                and tool.annotations.destructive_hint is False
                for tool in tools
            )
        )

    def test_patient_tool_uses_parameterized_select_and_returns_records(self) -> None:
        expected = {
            "source_table": "lab_results",
            "record_count": 1,
            "records": [{"test_name": "Synthetic test"}],
        }

        async def call_tool() -> object:
            async with Client(mcp_server.mcp) as client:
                return await client.call_tool(
                    "get_patient_records",
                    {
                        "synthetic_patient_id": "SYN-P-0001",
                        "category": "lab_results",
                        "limit": 4,
                    },
                )

        with patch.object(
            mcp_server,
            "_run_select",
            return_value=expected["records"],
        ) as run_select:
            result = asyncio.run(call_tool())

        run_select.assert_called_once()
        query, parameters = run_select.call_args.args
        self.assertIn("SELECT", query)
        self.assertIn("%s", query)
        self.assertNotIn("SYN-P-0001", query)
        self.assertEqual(parameters, ("SYN-P-0001", 4))
        content = next(block for block in result.content if isinstance(block, TextContent))
        self.assertEqual(json.loads(content.text), expected)

    def test_database_query_is_read_only_before_select(self) -> None:
        class FakeCursor:
            def fetchall(self) -> list[dict[str, int]]:
                return [{"record_count": 3}]

        class FakeConnection:
            def __init__(self) -> None:
                self.statements: list[tuple[str, tuple[object, ...] | None]] = []

            def __enter__(self) -> FakeConnection:
                return self

            def __exit__(self, *_: object) -> None:
                return None

            def execute(
                self,
                query: str,
                parameters: tuple[object, ...] | None = None,
            ) -> FakeCursor:
                self.statements.append((query, parameters))
                return FakeCursor()

        connection = FakeConnection()
        environment = {
            "MEDIASSIST_DB_HOST": "db.example.test",
            "MEDIASSIST_DB_PORT": "5432",
            "MEDIASSIST_DB_NAME": "defaultdb",
            "MEDIASSIST_DB_USER": "mediassist_reader",
            "MEDIASSIST_DB_PASSWORD": "test-only",
            "MEDIASSIST_DB_SSLMODE": "require",
        }

        with (
            patch.object(
                mcp_server,
                "get_mcp_database_environment",
                return_value=environment,
            ),
            patch.object(mcp_server.psycopg, "connect", return_value=connection),
        ):
            result = mcp_server._run_select(
                "SELECT COUNT(*) AS record_count FROM mediassist_demo.patients"
            )

        self.assertEqual(result, [{"record_count": 3}])
        self.assertEqual(connection.statements[0], ("SET TRANSACTION READ ONLY", None))
        self.assertTrue(connection.statements[1][0].lstrip().startswith("SELECT"))

    def test_sql_runner_rejects_non_select_statements(self) -> None:
        with self.assertRaisesRegex(ValueError, "predefined"):
            mcp_server._run_select("DELETE FROM mediassist_demo.patients")

    def test_sql_runner_rejects_unregistered_select_statements(self) -> None:
        with self.assertRaisesRegex(ValueError, "predefined"):
            mcp_server._run_select("SELECT * FROM mediassist_demo.patients")

    def test_patient_tools_reject_non_synthetic_identifiers(self) -> None:
        async def call_tool() -> object:
            async with Client(mcp_server.mcp) as client:
                return await client.call_tool(
                    "get_patient_overview",
                    {"synthetic_patient_id": "somebody@example.test"},
                )

        with patch.object(mcp_server, "_run_select") as run_select:
            result = asyncio.run(call_tool())

        self.assertTrue(result.is_error)
        run_select.assert_not_called()


class MCPDataAgentTests(unittest.TestCase):
    """Verify planner tasks map to a fixed tool and validated arguments."""

    def test_patient_task_selects_category_and_requires_exact_synthetic_id(self) -> None:
        task = PlannedTask(
            "labs",
            "Retrieve recent laboratory test results.",
            "mcp",
        )

        request, reason = MCPDataAgent._build_request(
            task,
            "Show lab results for SYN-P-0001.",
        )

        self.assertIsNotNone(request)
        self.assertEqual(reason, "")
        self.assertEqual(request.name, "get_patient_records")
        self.assertEqual(
            request.arguments,
            {
                "synthetic_patient_id": "SYN-P-0001",
                "category": "lab_results",
                "limit": 25,
            },
        )

        missing_id, missing_reason = MCPDataAgent._build_request(
            task,
            "Show recent lab results.",
        )

        self.assertIsNone(missing_id)
        self.assertIn("SYN-P-####", missing_reason)

    def test_aggregate_task_uses_allowlisted_table_count_tool(self) -> None:
        task = PlannedTask("count", "Count patient records.", "mcp")

        request, reason = MCPDataAgent._build_request(
            task,
            "How many patients are in the demo database?",
        )

        self.assertIsNotNone(request)
        self.assertEqual(reason, "")
        self.assertEqual(request.name, "count_demo_records")
        self.assertEqual(request.arguments, {"table_name": "patients"})

    def test_patient_specific_count_does_not_run_an_unfiltered_aggregate(self) -> None:
        task = PlannedTask("lab-count", "Count lab results.", "mcp")

        request, reason = MCPDataAgent._build_request(
            task,
            "How many lab results does SYN-P-0001 have?",
        )

        self.assertIsNone(request)
        self.assertIn("Patient-specific record counts are not supported", reason)


if __name__ == "__main__":
    unittest.main()

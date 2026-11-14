"""Verify workflow telemetry is opt-in and excludes user content."""

from __future__ import annotations

import logging
import os
import unittest
from unittest.mock import Mock, patch

from langsmith.run_helpers import tracing_context
from langsmith.utils import tracing_is_enabled

from mediassist_healthcare.agent_models import AgentWorkflowResult
from mediassist_healthcare.observability import (
    WorkflowObserver,
    log_safe_event,
    safe_exception_fields,
)
from mediassist_healthcare.settings import (
    get_langsmith_project_name,
    langsmith_tracing_is_enabled,
)


class ObservabilityTests(unittest.TestCase):
    """Test safe local logs, LangSmith opt-in, and metadata-only run payloads."""

    def test_langsmith_tracing_requires_explicit_opt_in(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(langsmith_tracing_is_enabled())

        with patch.dict(
            os.environ,
            {"MEDIASSIST_ENABLE_LANGSMITH": "true"},
            clear=True,
        ):
            self.assertTrue(langsmith_tracing_is_enabled())
            self.assertEqual(
                get_langsmith_project_name(),
                "mediassist-healthcare",
            )

    def test_graph_context_disables_ambient_langsmith_tracing(self) -> None:
        with patch.dict(os.environ, {"LANGSMITH_TRACING": "true"}):
            self.assertTrue(tracing_is_enabled())
            with tracing_context(enabled=False):
                self.assertFalse(tracing_is_enabled())

    def test_disabled_observer_does_not_create_external_traces(self) -> None:
        client = Mock()
        observer = WorkflowObserver(enabled=False, client=client)
        observation = observer.start("hybrid", 0)
        observation.finish(
            AgentWorkflowResult(
                answer="A private answer.",
                status="answered",
                citations=(),
                task_outcomes=(),
                intent="Private intent.",
                complexity="single_step",
                retrieval_mode="hybrid",
                model="test-model",
            ),
            duration_ms=10,
        )

        client.create_run.assert_not_called()

    def test_opt_in_without_api_key_does_not_construct_langsmith_client(self) -> None:
        with patch.dict(
            os.environ,
            {"MEDIASSIST_ENABLE_LANGSMITH": "true"},
            clear=True,
        ):
            with patch("mediassist_healthcare.observability.Client") as client_factory:
                observation = WorkflowObserver().start("hybrid", 0)

        self.assertIsNone(observation.root)
        client_factory.assert_not_called()

    def test_langsmith_client_hides_run_inputs_and_outputs(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MEDIASSIST_ENABLE_LANGSMITH": "true",
                "LANGSMITH_API_KEY": "test-key-not-a-real-credential",
            },
            clear=True,
        ):
            with patch("mediassist_healthcare.observability.Client") as client_factory:
                WorkflowObserver().start("hybrid", 0)

        client_factory.assert_called_once_with(
            timeout_ms=(2_000, 2_000),
            auto_batch_tracing=False,
            hide_inputs=True,
            hide_outputs=True,
        )

    def test_langsmith_trace_payloads_exclude_content_and_unknown_metadata(self) -> None:
        client = Mock()
        observer = WorkflowObserver(
            enabled=True,
            client=client,
            project_name="test-project",
        )
        observation = observer.start("hybrid", 1)
        observation.record_node(
            "Planner",
            "completed",
            4,
            {"task_count": 2, "question": "private question"},
        )
        observation.finish(
            AgentWorkflowResult(
                answer="Private answer text.",
                status="answered",
                citations=(),
                task_outcomes=(),
                intent="Private intent text.",
                complexity="single_step",
                retrieval_mode="hybrid",
                model="test-model",
            ),
            duration_ms=20,
        )

        self.assertEqual(client.create_run.call_count, 2)
        payload_text = repr(client.create_run.call_args_list)
        self.assertNotIn("private question", payload_text)
        self.assertNotIn("Private answer text", payload_text)
        self.assertNotIn("Private intent text", payload_text)
        self.assertIn("task_count", payload_text)
        self.assertIn("duration_ms", payload_text)
        planner_payload = next(
            call.kwargs
            for call in client.create_run.call_args_list
            if call.kwargs["name"] == "Planner"
        )
        self.assertEqual(
            {
                key: planner_payload["extra"]["metadata"][key]
                for key in ("node", "status", "duration_ms", "task_count")
            },
            {
                "node": "Planner",
                "status": "completed",
                "duration_ms": 4,
                "task_count": 2,
            },
        )

    def test_safe_logs_and_exception_summaries_exclude_exception_messages(self) -> None:
        logger = Mock(spec=logging.Logger)
        error = RuntimeError("Private prompt and extracted document text")

        log_safe_event(
            logger,
            "workflow.failed",
            exception_type="RuntimeError",
            question="private question",
            request_id="12345678-1234-1234-1234-123456789012",
        )
        fields = safe_exception_fields(error)

        message = logger.log.call_args.args[1]
        self.assertNotIn("private question", message)
        self.assertNotIn("Private prompt", message)
        self.assertEqual(fields, {"exception_type": "RuntimeError"})

    def test_error_summary_uses_status_and_safe_provider_code_only(self) -> None:
        error = ValueError("private message")
        error.status_code = 400
        error.code = "invalid_request"

        self.assertEqual(
            safe_exception_fields(error),
            {
                "exception_type": "ValueError",
                "provider_status": 400,
                "provider_code": "invalid_request",
            },
        )


if __name__ == "__main__":
    unittest.main()

"""Verify Phase 11 frontend session-state helpers."""

from __future__ import annotations

import unittest
from pathlib import Path

from mediassist_healthcare.frontend import (
    ChatExchange,
    SourceFile,
    add_source_file,
    build_dashboard_metrics,
    _dashboard_run,
    keep_recent_exchanges,
    remove_source_file,
    source_kind_for_filename,
)


class StreamlitFrontendStateTests(unittest.TestCase):
    """Test local chat history and source-list behavior without running Streamlit."""

    def test_chat_history_keeps_latest_five_pairs_in_fifo_order(self) -> None:
        exchanges = [
            ChatExchange(f"Question {number}", f"Answer {number}")
            for number in range(1, 8)
        ]

        recent = keep_recent_exchanges(exchanges)

        self.assertEqual(len(recent), 5)
        self.assertEqual(
            [exchange.question for exchange in recent],
            [
                "Question 3",
                "Question 4",
                "Question 5",
                "Question 6",
                "Question 7",
            ],
        )
        self.assertEqual(
            [exchange.answer for exchange in recent],
            ["Answer 3", "Answer 4", "Answer 5", "Answer 6", "Answer 7"],
        )

    def test_chat_history_keeps_all_exchanges_when_below_limit(self) -> None:
        exchanges = [ChatExchange("Question", "Answer")]

        self.assertEqual(keep_recent_exchanges(exchanges), exchanges)

    def test_dashboard_metrics_summarize_only_workflow_telemetry(self) -> None:
        response = {
            "answer": "Private response text",
            "question": "Private question text",
            "status": "partial",
            "citations": [{"source_type": "documents"}],
            "tasks": [
                {
                    "task_id": "policy",
                    "description": "Sensitive planned description",
                    "reason": "Sensitive model-generated reason",
                    "status": "completed",
                    "source": "documents",
                },
                {
                    "task_id": "claim",
                    "description": "Another sensitive task",
                    "reason": "Another sensitive reason",
                    "status": "incomplete",
                    "source": "mcp",
                },
            ],
            "traces": [
                {
                    "node": "Planner",
                    "status": "completed",
                    "duration_ms": 8,
                    "detail": "Created 2 tasks.",
                },
                {
                    "node": "Retriever",
                    "status": "completed",
                    "duration_ms": 20,
                    "detail": "Retrieved 1 passage.",
                },
            ],
        }

        record = _dashboard_run(response, 40, "2026-11-13T10:00:00+05:30")
        metrics = build_dashboard_metrics([record])

        self.assertNotIn("question", record)
        self.assertNotIn("answer", record)
        self.assertNotIn("Sensitive planned description", str(record))
        self.assertNotIn("Sensitive model-generated reason", str(record))
        self.assertEqual(metrics["total_runs"], 1)
        self.assertEqual(metrics["status_counts"], {"partial": 1})
        self.assertEqual(metrics["median_duration_ms"], 40)
        self.assertEqual(metrics["citation_count"], 1)
        self.assertEqual(metrics["completed_tasks"], 1)
        self.assertEqual(metrics["total_tasks"], 2)
        self.assertEqual(
            metrics["average_step_durations"],
            {"Planner": 8, "Retriever": 20},
        )

    def test_dashboard_page_renders_for_an_authenticated_session(self) -> None:
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(
            str(
                Path(__file__).resolve().parents[1]
                / "src"
                / "mediassist_healthcare"
                / "frontend.py"
            )
        )
        app.session_state["access_token"] = "test-token"
        app.session_state["authenticated_user"] = {
            "first_name": "Test",
            "last_name": "User",
        }
        app.session_state["backend_session_id"] = "test-session"
        app.session_state["workflow_runs"] = [
            _dashboard_run(
                {
                    "status": "answered",
                    "citations": [{"source_type": "documents"}],
                    "tasks": [{"status": "completed", "source": "documents"}],
                    "traces": [
                        {
                            "node": "Planner",
                            "status": "completed",
                            "duration_ms": 8,
                            "detail": "Created 1 task(s).",
                        }
                    ],
                },
                40,
            )
        ]

        app.run(timeout=8)
        self.assertFalse(app.exception)
        app.radio[0].set_value("Analytics dashboard").run(timeout=8)

        self.assertFalse(app.exception)
        markdown_values = [element.value for element in app.markdown]
        self.assertTrue(any("Workflow analytics" in value for value in markdown_values))
        self.assertTrue(any("Agent execution traces" in value for value in markdown_values))

    def test_add_source_file_appends_name_and_size(self) -> None:
        existing = [SourceFile("existing", "policy.pdf", 1024, "document")]

        updated = add_source_file(
            existing,
            "uploaded",
            "admission.pdf",
            2048,
            "document",
        )

        self.assertEqual(len(updated), 2)
        self.assertEqual(updated[0], existing[0])
        self.assertEqual(updated[1].name, "admission.pdf")
        self.assertEqual(updated[1].size_bytes, 2048)
        self.assertEqual(updated[1].file_id, "uploaded")

    def test_remove_source_file_only_removes_the_selected_file(self) -> None:
        sources = [
            SourceFile("first", "policy.pdf", 1024, "document"),
            SourceFile("second", "admission.pdf", 2048, "document"),
        ]

        remaining = remove_source_file(sources, "first")

        self.assertEqual(remaining, [sources[1]])
        self.assertEqual(len(sources), 2)

    def test_login_screen_precedes_uploads(self) -> None:
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(
            str(
                Path(__file__).resolve().parents[1]
                / "src"
                / "mediassist_healthcare"
                / "frontend.py"
            )
        )
        app = app.run(timeout=8)

        self.assertFalse(app.exception)
        self.assertEqual(len(app.file_uploader), 0)
        self.assertEqual(app.radio[0].value, "Log in")
        input_labels = [element.label for element in app.text_input]
        self.assertIn("Username", input_labels)
        self.assertIn("Password", input_labels)
        app.radio[0].set_value("Create account").run(timeout=8)
        self.assertEqual(app.radio[0].value, "Create account")
        input_labels = [element.label for element in app.text_input]
        password_input = next(
            element for element in app.text_input if element.label == "Create password"
        )
        self.assertEqual(password_input.placeholder, "Example: Snooker@147")
        self.assertIn("First name", input_labels)
        self.assertIn("Last name", input_labels)

    def test_completed_signup_redirects_to_login_and_prefills_username(self) -> None:
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(
            str(
                Path(__file__).resolve().parents[1]
                / "src"
                / "mediassist_healthcare"
                / "frontend.py"
            )
        )
        app.session_state["signup_completed"] = True
        app.session_state["new_account_username"] = "casey.user"
        app.session_state["auth_message"] = (
            "Your account has been created. Please log in with your new username "
            "and password."
        )
        app = app.run(timeout=8)

        self.assertFalse(app.exception)
        self.assertEqual(app.radio[0].value, "Log in")
        login_username = next(
            element for element in app.text_input if element.label == "Username"
        )
        self.assertEqual(login_username.value, "casey.user")
        self.assertTrue(
            any(
                "Please log in with your new username and password" in element.value
                for element in app.info
            )
        )

    def test_signed_in_screen_has_one_document_and_image_uploader(self) -> None:
        from streamlit.testing.v1 import AppTest

        app = AppTest.from_file(
            str(
                Path(__file__).resolve().parents[1]
                / "src"
                / "mediassist_healthcare"
                / "frontend.py"
            )
        )
        app.session_state["access_token"] = "test-access-token"
        app.session_state["authenticated_user"] = {
            "user_id": "71d831ab-49d5-44bc-9ed1-e92fb6f4a658",
            "first_name": "Test",
            "last_name": "User",
            "username": "test.user",
        }
        app.session_state["backend_session_id"] = (
            "71d831ab-49d5-44bc-9ed1-e92fb6f4a658"
        )
        app = app.run(timeout=8)

        self.assertFalse(app.exception)
        self.assertEqual(len(app.file_uploader), 1)
        self.assertEqual(
            app.file_uploader[0].proto.type,
            [
                ".pdf",
                ".docx",
                ".txt",
                ".png",
                ".jpg",
                ".jpeg",
                ".webp",
            ],
        )
        self.assertTrue(app.chat_input[0].proto.accept_file)

    def test_uploaded_file_extension_selects_the_correct_backend_kind(self) -> None:
        self.assertEqual(source_kind_for_filename("policy.PDF"), "document")
        self.assertEqual(source_kind_for_filename("report.docx"), "document")
        self.assertEqual(source_kind_for_filename("scan.jpeg"), "image")
        self.assertEqual(source_kind_for_filename("scan.webp"), "image")

    def test_unsupported_upload_extension_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "supported document or image"):
            source_kind_for_filename("data.csv")


if __name__ == "__main__":
    unittest.main()

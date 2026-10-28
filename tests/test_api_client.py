"""Verify Streamlit's HTTP client sends requests to Phase 12 endpoints."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from mediassist_healthcare.api_client import (
    APIClientError,
    ask_backend,
    delete_source,
    list_sources,
    upload_source,
)


class APIClientTests(unittest.TestCase):
    """Test request paths, payloads, and visible error handling."""

    def test_upload_posts_one_file_to_its_kind_endpoint(self) -> None:
        response = httpx.Response(
            201,
            json={"file_id": "file-1", "name": "admission.pdf"},
        )
        with patch(
            "mediassist_healthcare.api_client.httpx.post",
            return_value=response,
        ) as post:
            result = upload_source(
                "http://localhost:8000/",
                "session-id",
                "document",
                "admission.pdf",
                b"pdf-bytes",
                "application/pdf",
            )

        self.assertEqual(result["name"], "admission.pdf")
        self.assertEqual(
            post.call_args.args[0],
            "http://localhost:8000/api/sessions/session-id/documents",
        )
        self.assertEqual(
            post.call_args.kwargs["files"]["file"],
            ("admission.pdf", b"pdf-bytes", "application/pdf"),
        )

    def test_source_list_uses_the_current_session_endpoint(self) -> None:
        response = httpx.Response(200, json=[{"name": "admission.pdf"}])
        with patch(
            "mediassist_healthcare.api_client.httpx.get",
            return_value=response,
        ) as get:
            sources = list_sources("http://localhost:8000", "session-id")

        self.assertEqual(sources[0]["name"], "admission.pdf")
        self.assertEqual(
            get.call_args.args[0],
            "http://localhost:8000/api/sessions/session-id/sources",
        )

    def test_delete_raises_a_user_visible_error_for_api_failures(self) -> None:
        response = httpx.Response(
            404,
            json={"detail": "The requested source was not found."},
            request=httpx.Request(
                "DELETE",
                "http://localhost:8000/api/sessions/session-id/sources/file-id",
            ),
        )
        with patch(
            "mediassist_healthcare.api_client.httpx.delete",
            return_value=response,
        ):
            with self.assertRaisesRegex(APIClientError, "HTTP 404"):
                delete_source("http://localhost:8000", "session-id", "file-id")

    def test_chat_posts_question_and_retrieval_options(self) -> None:
        response = httpx.Response(
            200,
            json={"answer": "Use the admission SOP.", "citations": []},
        )
        with patch(
            "mediassist_healthcare.api_client.httpx.post",
            return_value=response,
        ) as post:
            result = ask_backend(
                "http://localhost:8000",
                "session-id",
                "How does admission work?",
            )

        self.assertEqual(result["answer"], "Use the admission SOP.")
        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "question": "How does admission work?",
                "mode": "hybrid",
                "top_k": 5,
            },
        )

    def test_connection_errors_are_reported_with_backend_guidance(self) -> None:
        with patch(
            "mediassist_healthcare.api_client.httpx.get",
            side_effect=httpx.ConnectError("refused"),
        ):
            with self.assertRaisesRegex(APIClientError, "Start the FastAPI backend"):
                list_sources("http://localhost:8000", "session-id")


if __name__ == "__main__":
    unittest.main()

"""Verify Streamlit's HTTP client sends requests to Phase 12 endpoints."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from mediassist_healthcare.api_client import (
    APIClientError,
    auth_error_message,
    ask_backend,
    delete_source,
    list_sources,
    login_user,
    logout_user,
    signup_user,
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
                "access-token",
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
        self.assertEqual(
            post.call_args.kwargs["headers"],
            {"Authorization": "Bearer access-token"},
        )

    def test_source_list_uses_the_current_session_endpoint(self) -> None:
        response = httpx.Response(200, json=[{"name": "admission.pdf"}])
        with patch(
            "mediassist_healthcare.api_client.httpx.get",
            return_value=response,
        ) as get:
            sources = list_sources("http://localhost:8000", "session-id", "token")

        self.assertEqual(sources[0]["name"], "admission.pdf")
        self.assertEqual(
            get.call_args.args[0],
            "http://localhost:8000/api/sessions/session-id/sources",
        )
        self.assertEqual(
            get.call_args.kwargs["headers"],
            {"Authorization": "Bearer token"},
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
                delete_source(
                    "http://localhost:8000",
                    "session-id",
                    "token",
                    "file-id",
                )

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
                "token",
                "How does admission work?",
            )

        self.assertEqual(result["answer"], "Use the admission SOP.")
        self.assertEqual(
            post.call_args.kwargs["json"],
            {
                "question": "How does admission work?",
                "mode": "hybrid",
                "top_k": 5,
                "image_source_ids": [],
                "history": [],
                "external_image_approved": False,
            },
        )
        self.assertEqual(
            post.call_args.kwargs["headers"],
            {"Authorization": "Bearer token"},
        )

    def test_chat_attached_images_use_the_guarded_multipart_route(self) -> None:
        response = httpx.Response(200, json={"answer": "The report states [I1]."})
        with patch(
            "mediassist_healthcare.api_client.httpx.post",
            return_value=response,
        ) as post:
            ask_backend(
                "http://localhost:8000",
                "session-id",
                "token",
                "Summarize this report",
                image_source_ids=["stored-image-id"],
                history=[{"question": "Prior question", "answer": "Prior answer"}],
                image_files=[
                    ("new-report.png", b"\x89PNG\r\n\x1a\nimage", "image/png")
                ],
                external_image_approved=True,
            )

        self.assertEqual(
            post.call_args.args[0],
            "http://localhost:8000/api/sessions/session-id/chat/with-images",
        )
        self.assertEqual(post.call_args.kwargs["data"]["question"], "Summarize this report")
        self.assertEqual(
            post.call_args.kwargs["data"]["image_source_ids"],
            '["stored-image-id"]',
        )
        self.assertEqual(post.call_args.kwargs["files"][0][1][0], "new-report.png")
        self.assertEqual(
            post.call_args.kwargs["data"]["external_image_approved"],
            "true",
        )

    def test_connection_errors_are_reported_with_backend_guidance(self) -> None:
        with patch(
            "mediassist_healthcare.api_client.httpx.get",
            side_effect=httpx.ConnectError("refused"),
        ):
            with self.assertRaisesRegex(APIClientError, "Start the FastAPI backend"):
                list_sources("http://localhost:8000", "session-id", "token")

    def test_signup_and_login_send_account_fields(self) -> None:
        response = httpx.Response(
            201,
            json={"user_id": "user-1", "username": "alex"},
        )
        with patch(
            "mediassist_healthcare.api_client.httpx.post",
            return_value=response,
        ) as post:
            signup_user(
                "http://localhost:8000",
                "Alex",
                "Morgan",
                "alex",
                "Correct-Horse-Battery-42",
                "Correct-Horse-Battery-42",
            )
            login_user(
                "http://localhost:8000",
                "alex",
                "Correct-Horse-Battery-42",
            )

        self.assertEqual(
            post.call_args_list[0].kwargs["json"],
            {
                "first_name": "Alex",
                "last_name": "Morgan",
                "username": "alex",
                "password": "Correct-Horse-Battery-42",
                "confirm_password": "Correct-Horse-Battery-42",
            },
        )
        self.assertEqual(
            post.call_args_list[1].args[0],
            "http://localhost:8000/api/auth/login",
        )

    def test_logout_sends_bearer_token_for_revocation(self) -> None:
        response = httpx.Response(204)
        with patch(
            "mediassist_healthcare.api_client.httpx.post",
            return_value=response,
        ) as post:
            logout_user("http://localhost:8000", "access-token")

        self.assertEqual(
            post.call_args.kwargs["headers"],
            {"Authorization": "Bearer access-token"},
        )


    def test_auth_errors_are_user_friendly_without_http_status_codes(self) -> None:
        login_error = APIClientError(
            "Backend returned HTTP 401: Username or password is incorrect.",
            status_code=401,
            detail="Username or password is incorrect.",
        )
        signup_error = APIClientError(
            "Backend returned HTTP 422: Password must start with an uppercase letter.",
            status_code=422,
            detail="Password must start with an uppercase letter.",
        )

        login_message = auth_error_message(login_error, "login")
        signup_message = auth_error_message(signup_error, "signup")

        self.assertIn("Check your username and password", login_message)
        self.assertNotIn("401", login_message)
        self.assertEqual(
            signup_message,
            "Password must start with an uppercase letter.",
        )
        self.assertNotIn("422", signup_message)


if __name__ == "__main__":
    unittest.main()

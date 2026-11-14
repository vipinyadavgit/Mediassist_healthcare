"""Verify FastAPI upload, source, search, and chat contracts offline."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient

from mediassist_healthcare.agent_Orchestration import AgentWorkflow
from mediassist_healthcare.backend import BackendService, create_app
from mediassist_healthcare.agent_models import (
    AgentCitation,
    AgentWorkflowResult,
    TaskOutcome,
    WorkflowTraceEntry,
)
from mediassist_healthcare.frontend import _dashboard_run, build_dashboard_metrics
from mediassist_healthcare.multimodal_agent import MultimodalAgent
from mediassist_healthcare.planner_agent import PlannerAgent
from mediassist_healthcare.reasoning_agent import ReasoningAgent
from mediassist_healthcare.retriever import RetrievedChunk, Retriever
from mediassist_healthcare.retriever_agent import RetrieverAgent


class FastAPIBackendTests(unittest.TestCase):
    """Exercise HTTP routes with local storage and mocked AI/vector components."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.session_id = "bf99bb77-146b-46c2-9cdf-37ebbaabc321"
        self.store = Mock()
        self.store.collection.delete = Mock()

        def index_chunks(chunks, embeddings, source, document_metadata=None):
            self.assertEqual(len(chunks), len(embeddings))
            self.assertTrue(source)
            self.assertIsNotNone(document_metadata)
            return len(chunks)

        self.store.index_chunks.side_effect = index_chunks
        self.embedder = Mock()
        self.embedder.embed_chunks.side_effect = lambda chunks: [
            [1.0, 0.0] for _ in chunks
        ]
        self.chunk = RetrievedChunk(
            record_id="record-1",
            text="Admissions require a completed intake form.",
            metadata={
                "source": "C:\\private\\server\\admission.txt",
                "filename": "admission.txt",
                "chunk_index": 0,
            },
            distance=0.1,
            fusion_score=0.03,
        )
        self.retriever = Mock()
        self.retriever.retrieve.return_value = [self.chunk]
        self.workflow = Mock()
        self.workflow.run.return_value = AgentWorkflowResult(
            answer="Complete the intake form [D1].",
            citations=(
                AgentCitation(
                    reference="D1",
                    source="admission.txt",
                    chunk_number=1,
                    source_type="documents",
                    distance=0.1,
                ),
            ),
            task_outcomes=(
                TaskOutcome(
                    task_id="policy_lookup",
                    description="Find the admission instructions.",
                    source="documents",
                    status="completed",
                    reason="The admission source supports the answer.",
                ),
            ),
            retrieval_mode="hybrid",
            model="test-model",
            status="answered",
            intent="Find admission instructions.",
            complexity="single_step",
            traces=(
                WorkflowTraceEntry(
                    node="Planner",
                    status="completed",
                    duration_ms=8,
                    detail="Classified request and created 1 task(s).",
                ),
                WorkflowTraceEntry(
                    node="Reasoning",
                    status="completed",
                    duration_ms=12,
                    detail="Checked citations and 1 task outcome(s).",
                ),
            ),
        )
        service = BackendService(
            upload_directory=root / "uploads",
            catalog_path=root / "catalog.sqlite3",
            store=self.store,
            embedder=self.embedder,
            retriever=self.retriever,
            agent_workflow=self.workflow,
        )
        self.service = service
        self.app = create_app(service)
        self.client = TestClient(self.app)
        signup = self.client.post(
            "/api/auth/signup",
            json={
                "first_name": "Test",
                "last_name": "User",
                "username": "test.user",
                "password": "Correct-Horse-Battery-42",
                "confirm_password": "Correct-Horse-Battery-42",
            },
        )
        self.assertEqual(signup.status_code, 201, signup.text)
        self.assertNotIn("access_token", signup.json())
        self.session_id = signup.json()["user_id"]
        login = self.client.post(
            "/api/auth/login",
            json={
                "username": "test.user",
                "password": "Correct-Horse-Battery-42",
            },
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.access_token = login.json()["access_token"]
        self.headers = {"Authorization": f"Bearer {self.access_token}"}
        self.client.headers.update(self.headers)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def upload_document(self) -> dict[str, object]:
        response = self.client.post(
            f"/api/sessions/{self.session_id}/documents",
            files={"file": ("admission.txt", b"Admission requires an intake form.")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

    def test_account_signup_login_me_and_logout(self) -> None:
        profile = self.client.get("/api/auth/me")
        self.assertEqual(profile.status_code, 200)
        self.assertEqual(profile.json()["username"], "test.user")
        self.assertNotIn("password", profile.text.casefold())

        signed_out = self.client.post("/api/auth/logout")
        self.assertEqual(signed_out.status_code, 200)
        revoked = self.client.get("/api/auth/me")
        self.assertEqual(revoked.status_code, 401)

        signed_in = self.client.post(
            "/api/auth/login",
            json={
                "username": "TEST.USER",
                "password": "Correct-Horse-Battery-42",
            },
        )
        self.assertEqual(signed_in.status_code, 200, signed_in.text)
        self.assertEqual(
            signed_in.json()["user"]["user_id"],
            self.session_id,
        )
        self.assertNotEqual(
            signed_in.json()["access_token"],
            self.access_token,
        )

    def test_signup_does_not_authenticate_and_requires_login(self) -> None:
        client = TestClient(self.app)
        created = client.post(
            "/api/auth/signup",
            json={
                "first_name": "New",
                "last_name": "Account",
                "username": "new.account",
                "password": "Strong-Password-123",
                "confirm_password": "Strong-Password-123",
            },
        )

        self.assertEqual(created.status_code, 201, created.text)
        self.assertNotIn("access_token", created.json())
        self.assertEqual(client.get("/api/auth/me").status_code, 401)

        login = client.post(
            "/api/auth/login",
            json={
                "username": "new.account",
                "password": "Strong-Password-123",
            },
        )
        self.assertEqual(login.status_code, 200, login.text)
        self.assertIn("access_token", login.json())

    def test_signup_rejects_mismatched_and_duplicate_credentials(self) -> None:
        mismatch = self.client.post(
            "/api/auth/signup",
            json={
                "first_name": "Another",
                "last_name": "User",
                "username": "another.user",
                "password": "Correct-Horse-Battery-42",
                "confirm_password": "Different-Horse-Battery-42",
            },
        )
        duplicate = self.client.post(
            "/api/auth/signup",
            json={
                "first_name": "Another",
                "last_name": "User",
                "username": "TEST.USER",
                "password": "Correct-Horse-Battery-42",
                "confirm_password": "Correct-Horse-Battery-42",
            },
        )
        bad_login = TestClient(self.app).post(
            "/api/auth/login",
            json={"username": "test.user", "password": "Incorrect-password-123"},
        )
        bad_username = TestClient(self.app).post(
            "/api/auth/login",
            json={"username": "missing.user", "password": "Correct-Horse-Battery-42"},
        )

        self.assertEqual(mismatch.status_code, 422)
        self.assertEqual(duplicate.status_code, 409)
        self.assertEqual(bad_login.status_code, 401)
        self.assertEqual(bad_username.status_code, 401)
        self.assertEqual(
            bad_login.json()["detail"],
            "Username or password is incorrect.",
        )
        self.assertEqual(bad_username.json()["detail"], bad_login.json()["detail"])

    def test_signup_returns_clear_password_policy_error(self) -> None:
        response = TestClient(self.app).post(
            "/api/auth/signup",
            json={
                "first_name": "Casey",
                "last_name": "Taylor",
                "username": "casey.user",
                "password": "snooker@147",
                "confirm_password": "snooker@147",
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            response.json()["detail"],
            "Password must start with an uppercase letter.",
        )

    def test_source_routes_require_bearer_authentication(self) -> None:
        unauthenticated = TestClient(self.app)
        response = unauthenticated.get(
            f"/api/sessions/{self.session_id}/sources"
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(
            response.headers["www-authenticate"],
            "Bearer",
        )

    def test_health_route_does_not_load_embedding_or_openai_services(self) -> None:
        response = self.client.get("/api/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")

    def test_document_upload_indexes_and_lists_one_source(self) -> None:
        uploaded = self.upload_document()

        self.assertEqual(uploaded["name"], "admission.txt")
        self.assertEqual(uploaded["kind"], "document")
        self.assertGreater(uploaded["indexed_chunks"], 0)
        self.assertIn("indexed", uploaded["message"])
        self.assertEqual(
            self.client.get(
                f"/api/sessions/{self.session_id}/sources"
            ).json()[0]["file_id"],
            uploaded["file_id"],
        )
        self.store.index_chunks.assert_called_once()
        metadata = self.store.index_chunks.call_args.kwargs["document_metadata"]
        self.assertEqual(metadata["session_id"], self.session_id)
        self.assertEqual(metadata["upload_id"], uploaded["file_id"])

    def test_image_upload_stores_source_without_claiming_ocr(self) -> None:
        response = self.client.post(
            f"/api/sessions/{self.session_id}/images",
            files={
                "file": (
                    "prescription.png",
                    b"\x89PNG\r\n\x1a\nimage bytes",
                    "image/png",
                )
            },
        )

        self.assertEqual(response.status_code, 201, response.text)
        self.assertEqual(response.json()["kind"], "image")
        self.assertEqual(response.json()["indexed_chunks"], 0)
        self.assertIn("OCR", response.json()["message"])
        self.store.index_chunks.assert_not_called()

    def test_image_upload_rejects_mismatched_file_signature(self) -> None:
        response = self.client.post(
            f"/api/sessions/{self.session_id}/images",
            files={"file": ("prescription.png", b"not a PNG", "image/png")},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("does not match", response.json()["detail"])

    def test_delete_requires_owning_session_and_removes_file_and_vectors(self) -> None:
        uploaded = self.upload_document()
        file_id = uploaded["file_id"]

        other_signup = self.client.post(
            "/api/auth/signup",
            json={
                "first_name": "Other",
                "last_name": "User",
                "username": "other.user",
                "password": "Another-Secure-Password-43",
                "confirm_password": "Another-Secure-Password-43",
            },
        )
        self.assertEqual(other_signup.status_code, 201, other_signup.text)
        other_client = TestClient(self.app)
        other_login = other_client.post(
            "/api/auth/login",
            json={
                "username": "other.user",
                "password": "Another-Secure-Password-43",
            },
        )
        self.assertEqual(other_login.status_code, 200, other_login.text)
        other_client.headers["Authorization"] = "Bearer " + other_login.json()[
            "access_token"
        ]
        denied = other_client.delete(
            f"/api/sessions/{self.session_id}/sources/{file_id}"
        )
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(
            len(self.client.get(
                f"/api/sessions/{self.session_id}/sources"
            ).json()),
            1,
        )

        deleted = self.client.delete(
            f"/api/sessions/{self.session_id}/sources/{file_id}"
        )
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(
            self.client.get(
                f"/api/sessions/{self.session_id}/sources"
            ).json(),
            [],
        )
        self.store.collection.delete.assert_called_once_with(
            where={
                "$and": [
                    {"session_id": self.session_id},
                    {"upload_id": file_id},
                ]
            }
        )

    def test_chat_and_search_are_limited_to_session_documents(self) -> None:
        self.upload_document()

        search_response = self.client.post(
            f"/api/sessions/{self.session_id}/search",
            json={"query": "intake form", "mode": "hybrid", "top_k": 3},
        )
        chat_response = self.client.post(
            f"/api/sessions/{self.session_id}/chat",
            json={"question": "What is needed for admission?"},
        )

        self.assertEqual(search_response.status_code, 200, search_response.text)
        self.assertEqual(search_response.json()[0]["source"], "admission.txt")
        self.assertEqual(chat_response.status_code, 200, chat_response.text)
        self.assertEqual(
            chat_response.json()["citations"][0]["source"],
            "admission.txt",
        )
        self.assertEqual(chat_response.json()["citations"][0]["reference"], "D1")
        self.assertEqual(chat_response.json()["tasks"][0]["status"], "completed")
        self.assertEqual(
            [trace["node"] for trace in chat_response.json()["traces"]],
            ["Planner", "Reasoning"],
        )
        self.assertEqual(
            self.retriever.retrieve.call_args.kwargs["metadata_filter"],
            {"session_id": self.session_id},
        )
        self.assertEqual(
            self.workflow.run.call_args.kwargs["session_id"],
            self.session_id,
        )

    def test_synthetic_prescription_upload_retrieval_chat_and_dashboard(self) -> None:
        prescription_text = (
            "Synthetic training prescription. "
            "Medication name: Samplemed. "
            "This is fictional data and is not for clinical use."
        )
        uploaded = self.client.post(
            f"/api/sessions/{self.session_id}/documents",
            files={
                "file": (
                    "synthetic-prescription.txt",
                    prescription_text.encode("utf-8"),
                    "text/plain",
                )
            },
        )
        self.assertEqual(uploaded.status_code, 201, uploaded.text)
        upload_metadata = self.store.index_chunks.call_args.kwargs["document_metadata"]
        upload_file_id = uploaded.json()["file_id"]

        self.store.collection.query.return_value = {
            "ids": [["synthetic-prescription-chunk-1"]],
            "documents": [[prescription_text]],
            "metadatas": [[
                {
                    "source": "synthetic-prescription.txt",
                    "filename": "synthetic-prescription.txt",
                    "chunk_index": 0,
                    "session_id": self.session_id,
                    "upload_id": upload_file_id,
                }
            ]],
            "distances": [[0.08]],
        }
        planner_client = Mock()
        planner_client.responses.create.return_value.output_text = json.dumps(
            {
                "in_scope": True,
                "intent": "Find the medication name in a synthetic document.",
                "complexity": "single_step",
                "tasks": [
                    {
                        "task_id": "prescription_lookup",
                        "description": "Identify the medication name shown.",
                        "source": "documents",
                    }
                ],
            }
        )
        reasoning_client = Mock()
        reasoning_client.responses.create.return_value.output_text = json.dumps(
            {
                "answer": "The synthetic prescription lists Samplemed [D1].",
                "tasks": [
                    {
                        "task_id": "prescription_lookup",
                        "completed": True,
                        "reason": "The uploaded synthetic document names Samplemed.",
                    }
                ],
            }
        )
        self.service._agent_workflow = AgentWorkflow(
            planner=PlannerAgent(client=planner_client, model_name="test-model"),
            retriever=RetrieverAgent(
                Retriever(self.store, embedder=self.embedder)
            ),
            multimodal=MultimodalAgent(),
            reasoner=ReasoningAgent(
                client=reasoning_client,
                model_name="test-model",
            ),
        )

        chat = self.client.post(
            f"/api/sessions/{self.session_id}/chat",
            json={
                "question": "What medication name is shown in this synthetic prescription?",
                "mode": "semantic",
            },
        )

        self.assertEqual(chat.status_code, 200, chat.text)
        self.assertEqual(chat.json()["status"], "answered")
        self.assertEqual(chat.json()["answer"], "The synthetic prescription lists Samplemed [D1].")
        self.assertEqual(chat.json()["citations"][0]["reference"], "D1")
        self.assertEqual(
            chat.json()["citations"][0]["source"],
            "synthetic-prescription.txt",
        )
        self.assertEqual(chat.json()["tasks"][0]["status"], "completed")
        self.assertEqual(upload_metadata["filename"], "synthetic-prescription.txt")
        self.assertEqual(upload_metadata["session_id"], self.session_id)
        self.store.collection.query.assert_called_once()
        self.assertEqual(
            self.store.collection.query.call_args.kwargs["where"],
            {"session_id": self.session_id},
        )

        dashboard_record = _dashboard_run(chat.json(), 125)
        dashboard_metrics = build_dashboard_metrics([dashboard_record])
        self.assertEqual(dashboard_metrics["answered_runs"], 1)
        self.assertEqual(dashboard_metrics["source_counts"]["documents"], 1)
        self.assertEqual(dashboard_metrics["completed_tasks"], 1)
        self.assertNotIn("Samplemed", str(dashboard_record))
        self.assertNotIn("synthetic-prescription.txt", str(dashboard_record))

    def test_chat_route_accepts_a_direct_image_attachment(self) -> None:
        image_bytes = b"\x89PNG\r\n\x1a\nvalid image payload"
        response = self.client.post(
            f"/api/sessions/{self.session_id}/chat/with-images",
            data={
                "question": "Read the visible report text",
                "image_source_ids": "[]",
                "history": "[]",
                "external_image_approved": "true",
            },
            files=[
                ("image_files", ("report.png", image_bytes, "image/png")),
            ],
        )

        self.assertEqual(response.status_code, 200, response.text)
        images = self.workflow.run.call_args.kwargs["images"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].name, "report.png")
        self.assertEqual(images[0].media_type, "image/png")
        self.assertEqual(images[0].content, image_bytes)

    def test_chat_failure_logs_safe_exception_type_without_request_content(self) -> None:
        self.workflow.run.side_effect = RuntimeError(
            "The planner could not classify and decompose this request."
        )

        with self.assertLogs("mediassist_healthcare.backend", level="WARNING") as logs:
            response = self.client.post(
                f"/api/sessions/{self.session_id}/chat",
                json={
                    "question": "What is the patient admission policy?",
                    "mode": "hybrid",
                    "top_k": 5,
                },
            )

        log_output = "\n".join(logs.output)
        self.assertEqual(response.status_code, 503)
        self.assertIn('"exception_type": "RuntimeError"', log_output)
        self.assertNotIn(
            "The planner could not classify and decompose this request.",
            log_output,
        )
        self.assertNotIn("patient admission policy", log_output)
        self.assertTrue(response.headers["X-Request-ID"])
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

    def test_unhandled_api_failure_returns_safe_error_and_request_id(self) -> None:
        def fail() -> None:
            raise RuntimeError("private query and provider response")

        self.app.add_api_route("/_test/unhandled", fail)
        with self.assertLogs("mediassist_healthcare.backend", level="WARNING") as logs:
            response = self.client.get("/_test/unhandled")

        self.assertEqual(response.status_code, 500)
        self.assertIn("request ID", response.json()["detail"])
        self.assertNotIn("private query", response.text)
        self.assertNotIn("provider response", "\n".join(logs.output))
        self.assertTrue(response.headers["X-Request-ID"])

    def test_rejects_unsupported_file_type_and_invalid_session_id(self) -> None:
        unsupported = self.client.post(
            f"/api/sessions/{self.session_id}/documents",
            files={"file": ("record.csv", b"a,b")},
        )
        invalid_session = self.client.get("/api/sessions/not-a-uuid/sources")

        self.assertEqual(unsupported.status_code, 422)
        self.assertIn("Unsupported document type", unsupported.json()["detail"])
        self.assertEqual(invalid_session.status_code, 422)

    def test_rejects_empty_extracted_document_text(self) -> None:
        response = self.client.post(
            f"/api/sessions/{self.session_id}/documents",
            files={"file": ("blank.txt", b"   \n")},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("No selectable text", response.json()["detail"])

    def test_rejects_document_larger_than_10_mb(self) -> None:
        response = self.client.post(
            f"/api/sessions/{self.session_id}/documents",
            files={"file": ("large.txt", b"a" * 10_000_001)},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("10 MB", response.json()["detail"])
        self.assertEqual(
            self.client.get(
                f"/api/sessions/{self.session_id}/sources"
            ).json(),
            [],
        )

    def test_rejects_image_larger_than_10_mb(self) -> None:
        response = self.client.post(
            f"/api/sessions/{self.session_id}/images",
            files={
                "file": (
                    "large.png",
                    b"\x89PNG\r\n\x1a\n" + b"a" * 10_000_000,
                    "image/png",
                )
            },
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("10 MB", response.json()["detail"])

    def test_rejects_malformed_pdf_without_exposing_storage_paths(self) -> None:
        response = self.client.post(
            f"/api/sessions/{self.session_id}/documents",
            files={"file": ("broken.pdf", b"not a valid PDF")},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("valid PDF", response.json()["detail"])
        self.assertNotIn("uploads", response.text)

    def test_rejects_malformed_docx_without_exposing_storage_paths(self) -> None:
        response = self.client.post(
            f"/api/sessions/{self.session_id}/documents",
            files={"file": ("broken.docx", b"not a valid DOCX")},
        )

        self.assertEqual(response.status_code, 422)
        self.assertIn("valid PDF, DOCX, or UTF-8 TXT", response.json()["detail"])
        self.assertNotIn("uploads", response.text)


if __name__ == "__main__":
    unittest.main()

"""Verify FastAPI upload, source, search, and chat contracts offline."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from fastapi.testclient import TestClient

from mediassist_healthcare.backend import BackendService, create_app
from mediassist_healthcare.rag import Citation, RAGResponse
from mediassist_healthcare.retriever import RetrievedChunk


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
        self.rag_engine = Mock()
        self.rag_engine.ask.return_value = RAGResponse(
            answer="Complete the intake form [1].",
            citations=[
                Citation(
                    reference="1",
                    source="C:\\private\\server\\admission.txt",
                    chunk_number=1,
                    distance=0.1,
                    metadata={},
                )
            ],
            retrieved_chunks=[self.chunk],
            retrieval_mode="hybrid",
            model="test-model",
            status="answered",
        )
        service = BackendService(
            upload_directory=root / "uploads",
            catalog_path=root / "catalog.sqlite3",
            store=self.store,
            embedder=self.embedder,
            retriever=self.retriever,
            rag_engine=self.rag_engine,
        )
        self.client = TestClient(create_app(service))

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def upload_document(self) -> dict[str, object]:
        response = self.client.post(
            f"/api/sessions/{self.session_id}/documents",
            files={"file": ("admission.txt", b"Admission requires an intake form.")},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()

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

        denied = self.client.delete(
            f"/api/sessions/3ebaf4a5-79b5-48be-8f52-17b992db4a01/sources/{file_id}"
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
        self.assertNotIn("C:\\private", chat_response.text)
        self.assertEqual(
            self.retriever.retrieve.call_args.kwargs["metadata_filter"],
            {"session_id": self.session_id},
        )
        self.assertEqual(
            self.rag_engine.ask.call_args.kwargs["metadata_filter"],
            {"session_id": self.session_id},
        )

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

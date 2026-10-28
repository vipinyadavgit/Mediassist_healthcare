"""Tests for storing document chunks and searching their embeddings with ChromaDB."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import chromadb

from mediassist_healthcare.vector_store import ChromaVectorStore


class ChromaVectorStoreTests(unittest.TestCase):
    """Check local storage, retrieval, model safety, and invalid input handling."""

    # Create an isolated in-memory ChromaDB collection for each test.
    def setUp(self) -> None:
        """Create a fresh ChromaDB client and redirect persistent-client creation."""
        self.client = chromadb.EphemeralClient()
        self.client_patch = patch(
            "mediassist_healthcare.vector_store.chromadb.PersistentClient",
            return_value=self.client,
        )
        self.client_patch.start()
        self.temp_directory = tempfile.TemporaryDirectory()
        self.store = ChromaVectorStore(
            persist_directory=Path(self.temp_directory.name) / "database",
            collection_name=f"test_{self._testMethodName}",
            embedding_model_name="example/test-model",
        )

    # Stop client substitution and remove the temporary directory after each test.
    def tearDown(self) -> None:
        """Restore the real ChromaDB constructor and clean up temporary files."""
        self.client_patch.stop()
        self.temp_directory.cleanup()

    # Check that indexed chunks retain text, source details, and searchable terms.
    def test_indexes_chunks_with_source_and_search_metadata(self) -> None:
        """Verify stored chunks retain source, position, and normalized terms."""
        source = Path(self.temp_directory.name) / "admission.txt"
        count = self.store.index_chunks(
            ["Admission begins at reception.", "Billing is completed at discharge."],
            [[1.0, 0.0], [0.0, 1.0]],
            source,
        )

        stored = self.store.collection.get(
            where={"source": str(source.resolve())},
            include=["documents", "metadatas"],
        )

        self.assertEqual(count, 2)
        self.assertEqual(
            stored["documents"],
            ["Admission begins at reception.", "Billing is completed at discharge."],
        )
        self.assertEqual(stored["metadatas"][0]["source"], str(source.resolve()))
        self.assertEqual(stored["metadatas"][0]["chunk_index"], 0)
        self.assertEqual(stored["metadatas"][0]["terms"], ["admission", "at", "begins", "reception"])

    # Check that reindexing a shorter source removes its former trailing chunks.
    def test_reindexing_removes_stale_chunks_from_the_same_source(self) -> None:
        """Verify replacing a source does not leave outdated chunk records."""
        source = Path(self.temp_directory.name) / "policy.txt"
        self.store.index_chunks(
            ["First chunk.", "Second chunk."],
            [[1.0, 0.0], [0.0, 1.0]],
            source,
        )

        self.store.index_chunks(["Updated policy."], [[1.0, 0.0]], source)
        stored = self.store.collection.get(
            where={"source": str(source.resolve())},
            include=["documents"],
        )

        self.assertEqual(stored["documents"], ["Updated policy."])

    # Reject mismatched chunk and vector counts before writing to the database.
    def test_rejects_mismatched_chunk_and_embedding_counts(self) -> None:
        """Verify each text chunk must have exactly one embedding vector."""
        with self.assertRaisesRegex(ValueError, "must match"):
            self.store.index_chunks(
                ["One chunk.", "Another chunk."],
                [[1.0, 0.0]],
                "source.txt",
            )

    # Check that custom scalar metadata is stored for later retrieval filtering.
    def test_indexes_custom_metadata_for_filtering(self) -> None:
        """Verify a caller-provided metadata field is queryable in ChromaDB."""
        self.store.index_chunks(
            ["Admission policy."],
            [[1.0, 0.0]],
            "admission.txt",
            document_metadata={"department": "admissions", "active": True},
        )

        stored = self.store.collection.get(
            where={"department": "admissions"},
            include=["metadatas"],
        )

        self.assertEqual(len(stored["ids"]), 1)
        self.assertTrue(stored["metadatas"][0]["active"])

    # Reject caller metadata that could break internal search fields or storage.
    def test_rejects_reserved_or_unsupported_metadata(self) -> None:
        """Verify internal fields and non-scalar values cannot be overridden."""
        with self.assertRaisesRegex(ValueError, "reserved"):
            self.store.index_chunks(
                ["Policy."],
                [[1.0, 0.0]],
                "source.txt",
                document_metadata={"terms": "override"},
            )
        with self.assertRaisesRegex(ValueError, "string, number, or boolean"):
            self.store.index_chunks(
                ["Policy."],
                [[1.0, 0.0]],
                "source.txt",
                document_metadata={"department": ["admissions"]},
            )

    # Reject an empty source reference before creating a stored record.
    def test_rejects_empty_source_path(self) -> None:
        """Verify indexed chunks always retain a useful source path."""
        with self.assertRaisesRegex(ValueError, "source document path is required"):
            self.store.index_chunks(["A chunk."], [[1.0, 0.0]], "  ")

    # Reject malformed vectors and blank text before persisting records.
    def test_rejects_blank_text_and_invalid_embeddings(self) -> None:
        """Verify empty chunks and non-finite vectors are not stored."""
        with self.assertRaisesRegex(ValueError, "Text chunk 1 is empty"):
            self.store.index_chunks(["  "], [[1.0, 0.0]], "source.txt")

        with self.assertRaisesRegex(ValueError, "finite values"):
            self.store.index_chunks(["Valid text."], [[float("nan")]], "source.txt")

    # Reject a different model when reopening a collection with stored vectors.
    def test_rejects_embedding_model_mismatch(self) -> None:
        """Verify indexed and query embeddings are required to use one model."""
        with self.assertRaisesRegex(ValueError, "Use the same model"):
            ChromaVectorStore(
                persist_directory=Path(self.temp_directory.name) / "database",
                collection_name=f"test_{self._testMethodName}",
                embedding_model_name="example/different-model",
            )

    # Reject collections whose existing vectors cannot be tied to a known model.
    def test_rejects_collection_without_embedding_model_metadata(self) -> None:
        """Verify unknown-model collections are not silently reused."""
        self.client.get_or_create_collection(
            name="unlabelled_collection",
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,
        )

        with self.assertRaisesRegex(ValueError, "does not record its embedding model"):
            ChromaVectorStore(
                persist_directory=Path(self.temp_directory.name) / "database",
                collection_name="unlabelled_collection",
                embedding_model_name="example/test-model",
            )

if __name__ == "__main__":
    unittest.main()

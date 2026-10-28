"""Tests for converting prepared text chunks into embedding vectors."""

import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from mediassist_healthcare.embeddings import DEFAULT_MODEL_NAME, HuggingFaceEmbedder


class HuggingFaceEmbedderTests(unittest.TestCase):
    """Check model setup, vector output, and invalid input handling."""

    # Check that the selected Hugging Face model is loaded by name.
    def test_loads_selected_model(self) -> None:
        model = Mock()
        sentence_transformer = Mock(return_value=model)
        fake_sentence_transformers = SimpleNamespace(
            SentenceTransformer=sentence_transformer
        )

        with patch.dict(
            sys.modules,
            {"sentence_transformers": fake_sentence_transformers},
        ):
            embedder = HuggingFaceEmbedder()

        sentence_transformer.assert_called_once_with(DEFAULT_MODEL_NAME)
        self.assertEqual(embedder.model_name, DEFAULT_MODEL_NAME)

    # Check that embedding calls are batched and request normalized vectors.
    def test_embeds_chunks_as_normalized_python_lists(self) -> None:
        model = Mock()
        model.encode.return_value.tolist.return_value = [
            [0.6, 0.8],
            [1.0, 0.0],
        ]
        sentence_transformer = Mock(return_value=model)
        fake_sentence_transformers = SimpleNamespace(
            SentenceTransformer=sentence_transformer
        )

        with patch.dict(
            sys.modules,
            {"sentence_transformers": fake_sentence_transformers},
        ):
            embedder = HuggingFaceEmbedder("example/test-model")
            vectors = embedder.embed_chunks(
                ["patient record", "hospital policy"],
                batch_size=8,
            )

        self.assertEqual(vectors, [[0.6, 0.8], [1.0, 0.0]])
        model.encode.assert_called_once_with(
            ["patient record", "hospital policy"],
            batch_size=8,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )

    # Check that empty input returns no vectors without running model inference.
    def test_empty_chunk_list_returns_empty_vectors(self) -> None:
        model = Mock()
        sentence_transformer = Mock(return_value=model)
        fake_sentence_transformers = SimpleNamespace(
            SentenceTransformer=sentence_transformer
        )

        with patch.dict(
            sys.modules,
            {"sentence_transformers": fake_sentence_transformers},
        ):
            embedder = HuggingFaceEmbedder()
            vectors = embedder.embed_chunks([])

        self.assertEqual(vectors, [])
        model.encode.assert_not_called()

    # Check that blank chunks are rejected instead of embedded silently.
    def test_rejects_blank_chunk(self) -> None:
        fake_sentence_transformers = SimpleNamespace(
            SentenceTransformer=Mock(return_value=Mock())
        )

        with patch.dict(
            sys.modules,
            {"sentence_transformers": fake_sentence_transformers},
        ):
            embedder = HuggingFaceEmbedder()
            with self.assertRaisesRegex(ValueError, "Text chunk 2 is empty"):
                embedder.embed_chunks(["valid content", "   "])

    # Check that a zero or negative batch size is rejected.
    def test_rejects_invalid_batch_size(self) -> None:
        fake_sentence_transformers = SimpleNamespace(
            SentenceTransformer=Mock(return_value=Mock())
        )

        with patch.dict(
            sys.modules,
            {"sentence_transformers": fake_sentence_transformers},
        ):
            embedder = HuggingFaceEmbedder()
            with self.assertRaisesRegex(ValueError, "batch_size must be greater than zero"):
                embedder.embed_chunks(["valid content"], batch_size=0)

    # Check that inconsistent vectors from a model raise a clear error.
    def test_rejects_inconsistent_vector_dimensions(self) -> None:
        model = Mock()
        model.encode.return_value.tolist.return_value = [[0.5, 0.5], [1.0]]
        fake_sentence_transformers = SimpleNamespace(
            SentenceTransformer=Mock(return_value=model)
        )

        with patch.dict(
            sys.modules,
            {"sentence_transformers": fake_sentence_transformers},
        ):
            embedder = HuggingFaceEmbedder()
            with self.assertRaisesRegex(RuntimeError, "invalid dimensions"):
                embedder.embed_chunks(["first chunk", "second chunk"])

    # Check that a model returning fewer vectors than inputs raises a clear error.
    def test_rejects_wrong_number_of_vectors(self) -> None:
        """Verify the output count matches the number of source chunks."""
        model = Mock()
        model.encode.return_value.tolist.return_value = [[0.5, 0.5]]
        fake_sentence_transformers = SimpleNamespace(
            SentenceTransformer=Mock(return_value=model)
        )

        with patch.dict(
            sys.modules,
            {"sentence_transformers": fake_sentence_transformers},
        ):
            embedder = HuggingFaceEmbedder()
            with self.assertRaisesRegex(RuntimeError, "different number of vectors"):
                embedder.embed_chunks(["first chunk", "second chunk"])

    # Check that a missing optional package produces installation guidance.
    def test_explains_how_to_install_optional_dependency(self) -> None:
        """Verify missing embedding support gives the optional install command."""
        with patch.dict(sys.modules, {"sentence_transformers": None}):
            with self.assertRaisesRegex(ImportError, "uv sync --extra embeddings"):
                HuggingFaceEmbedder()


if __name__ == "__main__":
    unittest.main()

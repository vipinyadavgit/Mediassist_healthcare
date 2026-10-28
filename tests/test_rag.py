"""Tests for Phase 10 semantic/hybrid retrieval and source-grounded answers."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import chromadb
from openai import OpenAIError

from mediassist_healthcare.rag import (
    RAGEngine,
    RAGGenerationError,
    _parse_metadata_filter,
)
from mediassist_healthcare.retriever import RetrievedChunk, Retriever
from mediassist_healthcare.settings import (
    DEFAULT_OPENAI_CHAT_MODEL,
    get_openai_chat_model_name,
)
from mediassist_healthcare.vector_store import ChromaVectorStore


class RetrieverTests(unittest.TestCase):
    """Check semantic, lexical, hybrid, and metadata-filtered retrieval."""

    # Create an isolated ChromaDB collection with reusable test passages.
    def setUp(self) -> None:
        """Create a local test collection and deterministic query embedder."""
        self.client = chromadb.EphemeralClient()
        self.client_patch = patch(
            "mediassist_healthcare.vector_store.chromadb.PersistentClient",
            return_value=self.client,
        )
        self.client_patch.start()
        self.temp_directory = tempfile.TemporaryDirectory()
        self.store = ChromaVectorStore(
            persist_directory=Path(self.temp_directory.name) / "database",
            collection_name=f"retrieval_{self._testMethodName}",
            embedding_model_name="example/retrieval-model",
        )
        self.embedder = Mock()
        self.embedder.embed_chunks.side_effect = self._embed_query
        self.store.index_chunks(
            [
                "Admission requires identity documents and a completed intake form.",
                "Billing requires insurance claim forms before discharge.",
                "The admission policy explains identity checks and intake steps.",
            ],
            [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0]],
            "hospital-guide.txt",
            document_metadata={"department": "admissions"},
        )
        self.store.index_chunks(
            ["Billing services process insurance claim paperwork."],
            [[0.8, 0.2]],
            "billing-guide.txt",
            document_metadata={"department": "finance"},
        )
        self.retriever = Retriever(self.store, embedder=self.embedder)

    # Stop client substitution and clean up temporary test storage.
    def tearDown(self) -> None:
        """Restore ChromaDB construction and remove temporary test files."""
        self.client_patch.stop()
        self.temp_directory.cleanup()

    # Map query topics to fixed vectors so ranking tests are deterministic.
    def _embed_query(self, text_chunks: list[str]) -> list[list[float]]:
        """Return synthetic query vectors for the test passages."""
        query = text_chunks[0].casefold()
        if "billing" in query or "insurance" in query:
            return [[0.0, 1.0]]
        if "claim" in query:
            return [[0.0, 1.0]]
        return [[1.0, 0.0]]

    # Check that semantic results follow ChromaDB vector distance order.
    def test_semantic_search_ranks_by_similarity(self) -> None:
        """Verify nearest vectors appear first with their distance metadata."""
        results = self.retriever.semantic_search("admission identity", top_k=2)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].metadata["source"], str(Path("hospital-guide.txt").resolve()))
        self.assertIsNotNone(results[0].distance)
        self.assertLessEqual(results[0].distance, results[1].distance)

    # Check that lexical search retrieves case-insensitive exact query terms.
    def test_lexical_search_returns_matching_chunks(self) -> None:
        """Verify normalized ChromaDB term metadata drives BM25 results."""
        results = self.retriever.lexical_search("INSURANCE claim", top_k=2)

        self.assertTrue(results)
        self.assertIn("claim", results[0].text.casefold())
        self.assertIsNotNone(results[0].lexical_rank)
        self.assertIsNone(results[0].distance)

    # Check that hybrid retrieval can return semantic and lexical evidence.
    def test_hybrid_search_fuses_vector_and_lexical_candidates(self) -> None:
        """Verify reciprocal-rank fusion returns candidates from both search lists."""
        results = self.retriever.hybrid_search("admission claim", top_k=4)
        result_sources = {chunk.metadata["source"] for chunk in results}

        self.assertIn(str(Path("hospital-guide.txt").resolve()), result_sources)
        self.assertIn(str(Path("billing-guide.txt").resolve()), result_sources)
        self.assertTrue(any(chunk.semantic_rank is not None for chunk in results))
        self.assertTrue(any(chunk.lexical_rank is not None for chunk in results))
        self.assertTrue(all(chunk.fusion_score > 0 for chunk in results))

    # Check that metadata filters apply to vector and lexical candidates.
    def test_metadata_filter_is_applied_to_hybrid_search(self) -> None:
        """Verify a filtered hybrid query returns no out-of-scope departments."""
        results = self.retriever.hybrid_search(
            "insurance billing",
            top_k=5,
            metadata_filter={"department": "admissions"},
        )

        self.assertTrue(results)
        self.assertTrue(
            all(chunk.metadata["department"] == "admissions" for chunk in results)
        )

    # Check that an empty metadata filter and internal field are rejected.
    def test_rejects_invalid_metadata_filters(self) -> None:
        """Verify callers cannot bypass filter requirements or inspect index terms."""
        with self.assertRaisesRegex(ValueError, "cannot be an empty"):
            self.retriever.semantic_search("admission", metadata_filter={})
        with self.assertRaisesRegex(ValueError, "internal search fields"):
            self.retriever.lexical_search(
                "admission",
                metadata_filter={
                    "$and": [{"terms": {"$contains": "admission"}}]
                },
            )

    # Check that unsupported K values and unknown search modes fail explicitly.
    def test_rejects_invalid_top_k_and_mode(self) -> None:
        """Verify search limits and retrieval modes are validated."""
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            self.retriever.hybrid_search("admission", top_k=101)
        with self.assertRaisesRegex(ValueError, "Unsupported retrieval mode"):
            self.retriever.retrieve("admission", mode="unknown")  # type: ignore[arg-type]

    # Check that empty queries do not trigger vector or lexical database searches.
    def test_empty_query_returns_no_results(self) -> None:
        """Verify blank and punctuation-only queries return no retrieval results."""
        with self.assertRaisesRegex(ValueError, "query cannot be empty"):
            self.retriever.semantic_search("   ")
        self.assertEqual(self.retriever.lexical_search("!!!"), [])


class RAGSettingsTests(unittest.TestCase):
    """Check that the chat model setting is independent of embedding settings."""

    # Read a configured chat model from the environment.
    def test_reads_configured_chat_model(self) -> None:
        """Verify OPENAI_CHAT_MODEL overrides the documented default."""
        with patch.dict("os.environ", {"OPENAI_CHAT_MODEL": "example/chat-model"}):
            self.assertEqual(get_openai_chat_model_name(), "example/chat-model")

    # Use the default chat model when no environment override exists.
    def test_uses_default_chat_model(self) -> None:
        """Verify a missing chat model setting uses the safe documented default."""
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(get_openai_chat_model_name(), DEFAULT_OPENAI_CHAT_MODEL)


class MetadataFilterCliTests(unittest.TestCase):
    """Check command-line filters preserve scalar metadata value types."""

    # Parse strings, numbers, and booleans without converting every value to text.
    def test_parses_scalar_metadata_values(self) -> None:
        """Verify CLI filter values match the types stored during document indexing."""
        self.assertEqual(
            _parse_metadata_filter("department=admissions"),
            ("department", "admissions"),
        )
        self.assertEqual(_parse_metadata_filter("page=3"), ("page", 3))
        self.assertEqual(_parse_metadata_filter("active=true"), ("active", True))


class RAGEngineTests(unittest.TestCase):
    """Check grounded generation, citations, privacy options, and provider errors."""

    # Create an engine with one predictable retrieved passage and mocked OpenAI.
    def setUp(self) -> None:
        """Create a mocked retrieval result and isolated Responses API client."""
        self.chunk = RetrievedChunk(
            record_id="chunk-1",
            text="Admission begins at the reception desk.",
            metadata={
                "source": "admission.pdf",
                "chunk_index": 2,
                "department": "admissions",
            },
            distance=0.12,
            semantic_rank=1,
        )
        self.retriever = Mock(spec=Retriever)
        self.retriever.retrieve.return_value = [self.chunk]
        self.client = Mock()
        self.client.responses.create.side_effect = [
            SimpleNamespace(output_text="IN_SCOPE"),
            SimpleNamespace(output_text="Admission begins at reception [1]."),
        ]
        self.engine = RAGEngine(
            retriever=self.retriever,
            client=self.client,
            model_name="example/chat-model",
        )

    # Check that retrieved evidence is cited in the answer and response metadata.
    def test_generates_answer_with_valid_source_citation(self) -> None:
        """Verify the OpenAI request includes evidence and disables response storage."""
        result = self.engine.ask("Where does admission begin?")

        self.assertEqual(result.answer, "Admission begins at reception [1].")
        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].reference, "[1]")
        self.assertEqual(result.citations[0].source, "admission.pdf")
        self.assertEqual(result.citations[0].chunk_number, 3)
        self.assertEqual(result.citations[0].metadata, {"department": "admissions"})
        self.assertEqual(result.model, "example/chat-model")
        self.assertEqual(result.status, "answered")
        self.assertEqual(self.client.responses.create.call_count, 2)
        request = self.client.responses.create.call_args_list[-1].kwargs
        self.assertIn("Admission begins at the reception desk.", request["input"])
        self.assertIn("[1]", request["input"])
        self.assertFalse(request["store"])

    # Decline unrelated questions before retrieval or answer generation.
    def test_out_of_scope_question_returns_redirect_without_retrieval(self) -> None:
        """Verify clearly unrelated topics do not query ChromaDB or generate answers."""
        self.client.responses.create.side_effect = [
            SimpleNamespace(output_text="OUT_OF_SCOPE")
        ]

        result = self.engine.ask("Can you recommend a movie?")

        self.assertEqual(result.status, "out_of_scope")
        self.assertIn("MediAssist healthcare policies", result.answer)
        self.assertEqual(result.citations, [])
        self.retriever.retrieve.assert_not_called()
        self.assertEqual(self.client.responses.create.call_count, 1)

    # Reject ambiguous classifier output without continuing into retrieval.
    def test_rejects_invalid_scope_classifier_label(self) -> None:
        """Verify only the expected scope labels are accepted."""
        self.client.responses.create.side_effect = [
            SimpleNamespace(output_text="Maybe healthcare?")
        ]

        with self.assertRaisesRegex(RAGGenerationError, "invalid label"):
            self.engine.ask("What is the admission policy?")

        self.retriever.retrieve.assert_not_called()

    # Check that retrieval mode, K, and metadata filters reach the retriever.
    def test_passes_retrieval_options_through(self) -> None:
        """Verify the pipeline uses the requested mode, top-K, and filter."""
        self.engine.ask(
            "Where does admission begin?",
            top_k=3,
            retrieval_mode="semantic",
            metadata_filter={"department": "admissions"},
        )

        self.retriever.retrieve.assert_called_once_with(
            "Where does admission begin?",
            mode="semantic",
            top_k=3,
            metadata_filter={"department": "admissions"},
        )

    # Avoid an external model call when no evidence was retrieved.
    def test_returns_clear_response_without_evidence(self) -> None:
        """Verify empty retrieval is reported without asking OpenAI to guess."""
        self.retriever.retrieve.return_value = []

        result = self.engine.ask("What does the policy say?")

        self.assertEqual(result.status, "insufficient_evidence")
        self.assertIn("could not find indexed source passages", result.answer)
        self.assertEqual(result.citations, [])
        self.assertEqual(self.client.responses.create.call_count, 1)

    # Reject an answer that cites a source reference not present in the context.
    def test_rejects_unsupported_citation_reference(self) -> None:
        """Verify generated citation markers must resolve to retrieved passages."""
        self.client.responses.create.side_effect = [
            SimpleNamespace(output_text="IN_SCOPE"),
            SimpleNamespace(output_text="Unsupported answer [2]."),
        ]

        with self.assertRaisesRegex(RAGGenerationError, "unsupported citation"):
            self.engine.ask("Where does admission begin?")

    # Reject generated answers that omit source references entirely.
    def test_rejects_answer_without_citation(self) -> None:
        """Verify an evidence-backed answer must cite a retrieved passage."""
        self.client.responses.create.side_effect = [
            SimpleNamespace(output_text="IN_SCOPE"),
            SimpleNamespace(output_text="Admission begins at reception."),
        ]

        with self.assertRaisesRegex(RAGGenerationError, "did not cite"):
            self.engine.ask("Where does admission begin?")

    # Surface OpenAI service errors instead of returning a success-shaped answer.
    def test_surfaces_openai_provider_errors(self) -> None:
        """Verify provider errors become explicit RAG generation failures."""
        self.client.responses.create.side_effect = [
            SimpleNamespace(output_text="IN_SCOPE"),
            OpenAIError("provider unavailable"),
        ]

        with self.assertRaisesRegex(RAGGenerationError, "answer generation failed"):
            self.engine.ask("Where does admission begin?")

    # Stop processing if the classifier service fails.
    def test_surfaces_scope_classifier_errors(self) -> None:
        """Verify an API error during scope classification prevents retrieval."""
        self.client.responses.create.side_effect = OpenAIError("provider unavailable")

        with self.assertRaisesRegex(RAGGenerationError, "scope classification failed"):
            self.engine.ask("Where does admission begin?")

        self.retriever.retrieve.assert_not_called()

    # Reject blank questions and invalid prompt-budget settings.
    def test_rejects_blank_question_and_invalid_context_budget(self) -> None:
        """Verify invalid questions and context budgets fail before generation."""
        with self.assertRaisesRegex(ValueError, "question cannot be empty"):
            self.engine.ask("   ")
        with self.assertRaisesRegex(ValueError, "max_context_characters"):
            RAGEngine(self.retriever, max_context_characters=0)

    # Check that the generated evidence context respects its configured size.
    def test_context_is_bounded(self) -> None:
        """Verify an unusually long chunk is truncated to the context limit."""
        long_chunk = RetrievedChunk(
            record_id="large",
            text="A" * 1000,
            metadata={"source": "large.pdf", "chunk_index": 0},
            distance=0.1,
        )
        self.retriever.retrieve.return_value = [long_chunk]
        engine = RAGEngine(
            retriever=self.retriever,
            client=self.client,
            max_context_characters=80,
        )

        engine.ask("Summarize this document.")
        prompt = self.client.responses.create.call_args_list[-1].kwargs["input"]
        context = prompt.split("Reference passages:\n", maxsplit=1)[1]
        self.assertLessEqual(len(context.split("\n\nAnswer using only", maxsplit=1)[0]), 80)

    # Check that real retrieval feeds citations into a mocked answer-generation call.
    def test_end_to_end_hybrid_rag_returns_retrieved_citation(self) -> None:
        """Verify ChromaDB search, hybrid fusion, and RAG citation mapping work together."""
        with tempfile.TemporaryDirectory() as temp_dir:
            client = chromadb.EphemeralClient()
            with patch(
                "mediassist_healthcare.vector_store.chromadb.PersistentClient",
                return_value=client,
            ):
                store = ChromaVectorStore(
                    persist_directory=Path(temp_dir) / "database",
                    collection_name="end_to_end_rag",
                    embedding_model_name="example/retrieval-model",
                )
                store.index_chunks(
                    ["Admission begins at the reception desk."],
                    [[1.0, 0.0]],
                    "admission-guide.txt",
                    document_metadata={"department": "admissions"},
                )
                embedder = Mock()
                embedder.embed_chunks.return_value = [[1.0, 0.0]]
                retriever = Retriever(store=store, embedder=embedder)
                self.client.responses.create.side_effect = [
                    SimpleNamespace(output_text="IN_SCOPE"),
                    SimpleNamespace(
                        output_text="Admission begins at the reception desk [1]."
                    ),
                ]
                engine = RAGEngine(
                    retriever=retriever,
                    client=self.client,
                    model_name="example/chat-model",
                )

                result = engine.ask(
                    "Where does admission begin?",
                    metadata_filter={"department": "admissions"},
                )

        self.assertEqual(len(result.citations), 1)
        self.assertEqual(result.citations[0].source, str(Path("admission-guide.txt").resolve()))
        self.assertEqual(result.citations[0].chunk_number, 1)
        self.assertIn("[1]", result.answer)
        self.assertEqual(result.status, "answered")


if __name__ == "__main__":
    unittest.main()

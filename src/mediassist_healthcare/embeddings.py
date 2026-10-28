"""Create local Hugging Face embeddings from prepared document chunks.

This module implements Phase 6: it loads one document, applies the Phase 5
chunking strategy, and converts each chunk into a normalized numeric vector.
It does not save vectors or build a vector database.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mediassist_healthcare.ingestion import load_document
from mediassist_healthcare.text_processing import (
    chunk_by_characters,
    chunk_by_paragraph,
    chunk_by_sentence,
)
from mediassist_healthcare.settings import get_embedding_model_name

DEFAULT_MODEL_NAME = get_embedding_model_name()


class HuggingFaceEmbedder:
    """Load a local Sentence Transformers model and embed text chunks."""

    # Load the selected Hugging Face model when an embedder is created.
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME) -> None:
        """Create a local embedding model, downloading it on first use if needed."""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as error:
            raise ImportError(
                "Embedding support is optional. Install it with "
                "'uv sync --extra embeddings'."
            ) from error

        self.model_name = model_name
        self._model = SentenceTransformer(model_name)

    # Convert a list of prepared chunks into normalized numeric vectors.
    def embed_chunks(
        self,
        text_chunks: list[str],
        batch_size: int = 32,
    ) -> list[list[float]]:
        """Return one normalized embedding vector for each non-empty text chunk."""
        if batch_size < 1:
            raise ValueError("batch_size must be greater than zero.")

        for position, text in enumerate(text_chunks, start=1):
            if not text.strip():
                raise ValueError(f"Text chunk {position} is empty.")

        if not text_chunks:
            return []

        encoded_vectors = self._model.encode(
            text_chunks,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        vectors = [
            [float(value) for value in vector]
            for vector in encoded_vectors.tolist()
        ]

        if len(vectors) != len(text_chunks):
            raise RuntimeError(
                "The embedding model returned a different number of vectors "
                "than the number of input chunks."
            )

        vector_dimensions = {len(vector) for vector in vectors}
        if len(vector_dimensions) != 1 or 0 in vector_dimensions:
            raise RuntimeError(
                "The embedding model returned vectors with invalid dimensions."
            )

        return vectors


# Load one source document, create its chunks, and report embedding dimensions.
def main() -> None:
    """Run the Phase 6 embedding pipeline for one document from the command line."""
    parser = argparse.ArgumentParser(
        description="Create local embeddings for one PDF, DOCX, or TXT document."
    )
    parser.add_argument("file", type=Path, help="Path to one supported document")
    parser.add_argument(
        "--strategy",
        choices=("paragraph", "sentence", "character"),
        default="paragraph",
        help="Phase 5 chunking strategy to use (default: paragraph)",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=1000,
        help="Maximum characters in a chunk (default: 1000)",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=100,
        help="Overlap for character chunks (default: 100)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Number of chunks to embed at a time (default: 32)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_NAME,
        help=f"Hugging Face model ID (default: {DEFAULT_MODEL_NAME})",
    )
    args = parser.parse_args()

    document = load_document(args.file)
    if args.strategy == "paragraph":
        text_chunks = chunk_by_paragraph(document.text, args.max_chars)
    elif args.strategy == "sentence":
        text_chunks = chunk_by_sentence(document.text, args.max_chars)
    else:
        text_chunks = chunk_by_characters(
            document.text,
            max_chars=args.max_chars,
            overlap=args.overlap,
        )

    print(f"Source: {document.source}")
    print(f"Chunking strategy: {args.strategy}")
    print(f"Chunks: {len(text_chunks)}")

    if not text_chunks:
        print("No text was found to embed.")
        return

    embedder = HuggingFaceEmbedder(model_name=args.model)
    vectors = embedder.embed_chunks(text_chunks, batch_size=args.batch_size)
    print(f"Embedding model: {embedder.model_name}")
    print(f"Vectors created: {len(vectors)}")
    print(f"Dimensions per vector: {len(vectors[0])}")
    print("Vectors are normalized and have not been saved.")


# Run the command-line pipeline only when this file is executed directly.
if __name__ == "__main__":
    main()

"""Persist and search document embeddings with a local ChromaDB collection.

This module implements Phase 8: it prepares one document, stores its chunks
and supplied embeddings in a persistent local database, and exposes the
collection for retrieval by the dedicated Phase 10 retriever.
"""

from __future__ import annotations

import argparse
import hashlib
import math
import re
from pathlib import Path
from typing import TypeAlias

import chromadb

from mediassist_healthcare.embeddings import DEFAULT_MODEL_NAME, HuggingFaceEmbedder
from mediassist_healthcare.ingestion import load_document
from mediassist_healthcare.settings import PROJECT_ROOT
from mediassist_healthcare.text_processing import (
    chunk_by_characters,
    chunk_by_paragraph,
    chunk_by_sentence,
)

DEFAULT_PERSIST_DIRECTORY = PROJECT_ROOT / "output" / "chroma_db"
DEFAULT_COLLECTION_NAME = "mediassist_knowledge_base"
MetadataValue: TypeAlias = str | int | float | bool


class ChromaVectorStore:
    """Persist prepared document chunks and expose their ChromaDB collection."""

    # Open a persistent ChromaDB collection and check its embedding model.
    def __init__(
        self,
        persist_directory: str | Path = DEFAULT_PERSIST_DIRECTORY,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        embedding_model_name: str = DEFAULT_MODEL_NAME,
    ) -> None:
        """Create or open the local collection used for MediAssist documents."""
        self.embedding_model_name = embedding_model_name
        self.persist_directory = Path(persist_directory)
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        client = chromadb.PersistentClient(path=str(self.persist_directory))
        self._collection = client.get_or_create_collection(
            name=collection_name,
            metadata={
                "hnsw:space": "cosine",
                "embedding_model": embedding_model_name,
            },
            embedding_function=None,
        )

        stored_metadata = self._collection.metadata or {}
        stored_model_name = stored_metadata.get("embedding_model")
        if not stored_model_name:
            raise ValueError(
                "The collection does not record its embedding model. Select a "
                "new collection to avoid mixing incompatible embeddings."
            )
        if stored_model_name != embedding_model_name:
            raise ValueError(
                "The collection uses embedding model "
                f"'{stored_model_name}', not '{embedding_model_name}'. "
                "Use the same model for indexing and search, or select a "
                "different collection."
            )

    # Validate and persist chunk text, metadata, and matching embedding vectors.
    def index_chunks(
        self,
        text_chunks: list[str],
        embeddings: list[list[float]],
        source: str | Path,
        document_metadata: dict[str, MetadataValue] | None = None,
    ) -> int:
        """Upsert document chunks, searchable terms, and caller-supplied metadata."""
        if not text_chunks:
            raise ValueError("At least one text chunk is required.")
        if len(text_chunks) != len(embeddings):
            raise ValueError(
                "The number of text chunks must match the number of embeddings."
            )

        source_text = str(source).strip()
        if not source_text:
            raise ValueError("A source document path is required.")
        normalized_source = str(Path(source_text).expanduser().resolve())
        additional_metadata = document_metadata or {}
        reserved_metadata_keys = {"source", "chunk_index", "terms"}
        for key, value in additional_metadata.items():
            if not key.strip():
                raise ValueError("Metadata field names cannot be empty.")
            if key != key.strip():
                raise ValueError("Metadata field names cannot start or end with spaces.")
            if key in reserved_metadata_keys:
                raise ValueError(
                    f"Metadata field '{key}' is reserved for vector-store use."
                )
            if not isinstance(value, (str, int, float, bool)):
                raise ValueError(
                    f"Metadata field '{key}' must be a string, number, or boolean."
                )
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError(f"Metadata field '{key}' must be finite.")

        vector_dimensions: set[int] = set()
        for position, (text, vector) in enumerate(
            zip(text_chunks, embeddings, strict=True),
            start=1,
        ):
            if not text.strip():
                raise ValueError(f"Text chunk {position} is empty.")
            if not vector or any(not math.isfinite(value) for value in vector):
                raise ValueError(f"Embedding {position} must contain finite values.")
            vector_dimensions.add(len(vector))

        if len(vector_dimensions) != 1:
            raise ValueError("All embeddings must have the same number of dimensions.")

        chunk_ids = [
            hashlib.sha256(
                f"{normalized_source}\0{chunk_index}".encode("utf-8")
            ).hexdigest()
            for chunk_index in range(len(text_chunks))
        ]
        metadata = [
            {
                **additional_metadata,
                "source": normalized_source,
                "chunk_index": chunk_index,
                "terms": sorted(set(re.findall(r"\w+", text.casefold())))
                or ["__no_search_terms__"],
            }
            for chunk_index, text in enumerate(text_chunks)
        ]

        self._collection.upsert(
            ids=chunk_ids,
            documents=text_chunks,
            embeddings=embeddings,
            metadatas=metadata,
        )

        existing_ids = self._collection.get(
            where={"source": normalized_source},
            include=["metadatas"],
        )["ids"]
        stale_ids = sorted(set(existing_ids) - set(chunk_ids))
        if stale_ids:
            self._collection.delete(ids=stale_ids)

        return len(text_chunks)

    @property
    def collection(self) -> chromadb.Collection:
        """Expose the collection to the dedicated retrieval component."""
        return self._collection


# Add the shared database options to either command-line operation.
def _add_database_arguments(parser: argparse.ArgumentParser) -> None:
    """Configure local database path and collection options for a CLI command."""
    parser.add_argument(
        "--db-path",
        type=Path,
        default=DEFAULT_PERSIST_DIRECTORY,
        help=f"Local ChromaDB directory (default: {DEFAULT_PERSIST_DIRECTORY})",
    )
    parser.add_argument(
        "--collection",
        default=DEFAULT_COLLECTION_NAME,
        help=f"ChromaDB collection name (default: {DEFAULT_COLLECTION_NAME})",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL_NAME,
        help=f"Hugging Face model ID (default: {DEFAULT_MODEL_NAME})",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Number of chunks to embed at a time (default: 32)",
    )


# Prepare one document's text chunks using the selected Phase 5 strategy.
def _create_chunks(
    text: str,
    strategy: str,
    max_chars: int,
    overlap: int,
) -> list[str]:
    """Apply the selected chunking method before document embeddings are created."""
    if strategy == "paragraph":
        return chunk_by_paragraph(text, max_chars)
    if strategy == "sentence":
        return chunk_by_sentence(text, max_chars)
    return chunk_by_characters(text, max_chars, overlap)


# Parse one optional document metadata entry from the command line.
def _parse_document_metadata(value: str) -> tuple[str, MetadataValue]:
    """Convert FIELD=VALUE into a ChromaDB-compatible scalar metadata entry."""
    field, separator, raw_value = value.partition("=")
    if not separator or not field.strip() or not raw_value.strip():
        raise argparse.ArgumentTypeError(
            "Document metadata must use the form FIELD=VALUE."
        )
    if field.strip() in {"source", "chunk_index", "terms"}:
        raise argparse.ArgumentTypeError(
            f"The '{field.strip()}' metadata field is reserved."
        )
    cleaned_value = raw_value.strip()
    if cleaned_value.casefold() in {"true", "false"}:
        return field.strip(), cleaned_value.casefold() == "true"
    try:
        return field.strip(), int(cleaned_value)
    except ValueError:
        try:
            return field.strip(), float(cleaned_value)
        except ValueError:
            return field.strip(), cleaned_value


# Index one document or run semantic search through the retrieval component.
def main() -> None:
    """Run the Phase 8 ChromaDB indexing or semantic-search command."""
    parser = argparse.ArgumentParser(
        description="Index one document or search the local ChromaDB collection."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    index_parser = subparsers.add_parser(
        "index",
        help="Chunk and store one PDF, DOCX, or TXT document",
    )
    index_parser.add_argument("file", type=Path, help="Path to one supported document")
    index_parser.add_argument(
        "--strategy",
        choices=("paragraph", "sentence", "character"),
        default="paragraph",
        help="Phase 5 chunking strategy (default: paragraph)",
    )
    index_parser.add_argument(
        "--max-chars",
        type=int,
        default=1000,
        help="Maximum characters in a chunk (default: 1000)",
    )
    index_parser.add_argument(
        "--overlap",
        type=int,
        default=100,
        help="Character overlap for the character strategy (default: 100)",
    )
    index_parser.add_argument(
        "--metadata",
        action="append",
        type=_parse_document_metadata,
        default=[],
        metavar="FIELD=VALUE",
        help="Attach filterable document metadata; may be supplied more than once",
    )
    _add_database_arguments(index_parser)

    search_parser = subparsers.add_parser(
        "search",
        help="Search stored chunks using a natural-language query",
    )
    search_parser.add_argument("query", help="Text to search for")
    search_parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Maximum matching chunks to display (default: 5)",
    )
    _add_database_arguments(search_parser)

    args = parser.parse_args()
    document_metadata: dict[str, MetadataValue] = {}
    if args.command == "index":
        for field, value in args.metadata:
            if field in document_metadata:
                parser.error(f"Document metadata field '{field}' was supplied twice.")
            document_metadata[field] = value
    store = ChromaVectorStore(
        persist_directory=args.db_path,
        collection_name=args.collection,
        embedding_model_name=args.model,
    )

    if args.command == "index":
        embedder = HuggingFaceEmbedder(model_name=args.model)
        document = load_document(args.file)
        chunks = _create_chunks(
            document.text,
            args.strategy,
            args.max_chars,
            args.overlap,
        )
        if not chunks:
            print(f"No text was found in {document.source}; nothing was indexed.")
            return

        vectors = embedder.embed_chunks(chunks, batch_size=args.batch_size)
        indexed_count = store.index_chunks(
            chunks,
            vectors,
            document.source,
            document_metadata=document_metadata or None,
        )
        print(f"Source: {document.source}")
        print(f"Chunks indexed: {indexed_count}")
        print(f"Embedding model: {embedder.model_name}")
        print(f"Database: {args.db_path}")
    else:
        if not args.query.strip():
            parser.error("The search query cannot be empty.")
        from mediassist_healthcare.retriever import Retriever

        embedder = HuggingFaceEmbedder(model_name=args.model)
        retriever = Retriever(store=store, embedder=embedder)
        results = retriever.semantic_search(args.query, top_k=args.top_k)
        if not results:
            print("No indexed chunks were found.")
            return

        for rank, result in enumerate(results, start=1):
            distance = (
                f"{result.distance:.4f}" if result.distance is not None else "n/a"
            )
            print(
                f"{rank}. {result.metadata['source']} "
                f"(chunk {int(result.metadata['chunk_index']) + 1}, "
                f"distance {distance})"
            )
            print(result.text)
            print()


# Run the indexing and search CLI only when this file is executed directly.
if __name__ == "__main__":
    main()

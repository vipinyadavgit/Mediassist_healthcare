"""Retrieve and rank document chunks from the MediAssist ChromaDB collection.

This module implements the retrieval layer for Phase 10. It provides semantic,
lexical, and hybrid search, supports ChromaDB metadata filters, and keeps
retrieval logic separate from document persistence and answer generation.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Literal

from mediassist_healthcare.embeddings import HuggingFaceEmbedder
from mediassist_healthcare.vector_store import ChromaVectorStore

RetrievalMode = Literal["semantic", "lexical", "hybrid"]
MetadataFilter = dict[str, object]
_TOKEN_PATTERN = re.compile(r"\w+", flags=re.UNICODE)
_RESERVED_FILTER_FIELDS = {"terms"}
_MAX_TOP_K = 100
_DEFAULT_LEXICAL_CANDIDATE_LIMIT = 1000
_DEFAULT_RRF_CONSTANT = 60


@dataclass(frozen=True)
class RetrievedChunk:
    """Keep a retrieved passage, ranking details, and safe citation metadata."""

    record_id: str
    text: str
    metadata: dict[str, object]
    distance: float | None = None
    semantic_rank: int | None = None
    lexical_rank: int | None = None
    fusion_score: float = 0.0
    tokenized_terms: list[str] = field(default_factory=list, repr=False)


class Retriever:
    """Run semantic, BM25 lexical, and rank-fused hybrid retrieval."""

    # Configure the collection, embedding model, and bounded lexical search pool.
    def __init__(
        self,
        store: ChromaVectorStore,
        embedder: HuggingFaceEmbedder | None = None,
        lexical_candidate_limit: int = _DEFAULT_LEXICAL_CANDIDATE_LIMIT,
        rrf_constant: int = _DEFAULT_RRF_CONSTANT,
    ) -> None:
        """Create a retriever for an existing ChromaDB collection."""
        if lexical_candidate_limit < 1:
            raise ValueError("lexical_candidate_limit must be greater than zero.")
        if rrf_constant < 1:
            raise ValueError("rrf_constant must be greater than zero.")

        self.store = store
        self._embedder = embedder
        self.lexical_candidate_limit = lexical_candidate_limit
        self.rrf_constant = rrf_constant

    # Convert query text to tokens, rejecting empty or unusable queries.
    def _query_terms(self, query: str) -> list[str]:
        """Normalize a user query into unique case-insensitive search terms."""
        if not query.strip():
            raise ValueError("The search query cannot be empty.")
        return list(dict.fromkeys(_TOKEN_PATTERN.findall(query.casefold())))

    # Validate positive result limits and keep retrieval requests bounded.
    def _validate_top_k(self, top_k: int) -> None:
        """Reject result counts outside the supported safe range."""
        if top_k < 1 or top_k > _MAX_TOP_K:
            raise ValueError(f"top_k must be between 1 and {_MAX_TOP_K}.")

    # Validate and normalize metadata filters before passing them to ChromaDB.
    def _validate_metadata_filter(
        self,
        metadata_filter: MetadataFilter | None,
    ) -> MetadataFilter | None:
        """Reject internal indexing fields from caller-provided metadata filters."""
        if metadata_filter is None:
            return None
        if not metadata_filter:
            raise ValueError("metadata_filter cannot be an empty dictionary.")
        if self._contains_reserved_filter_field(metadata_filter):
            raise ValueError("Metadata filters cannot use internal search fields.")
        return metadata_filter

    # Inspect nested ChromaDB where expressions for reserved internal fields.
    def _contains_reserved_filter_field(self, value: object) -> bool:
        """Return whether a nested metadata filter references internal fields."""
        if isinstance(value, dict):
            if _RESERVED_FILTER_FIELDS.intersection(value):
                return True
            return any(
                self._contains_reserved_filter_field(nested_value)
                for nested_value in value.values()
            )
        if isinstance(value, list):
            return any(
                self._contains_reserved_filter_field(nested_value)
                for nested_value in value
            )
        return False

    # Embed a text query and return the nearest vector matches from ChromaDB.
    def semantic_search(
        self,
        query: str,
        top_k: int = 5,
        metadata_filter: MetadataFilter | None = None,
    ) -> list[RetrievedChunk]:
        """Return the closest matching chunks using ChromaDB cosine distance."""
        self._validate_top_k(top_k)
        if not self._query_terms(query):
            return []
        validated_filter = self._validate_metadata_filter(metadata_filter)
        if self._embedder is None:
            self._embedder = HuggingFaceEmbedder(
                model_name=self.store.embedding_model_name
            )
        query_embedding = self._embedder.embed_chunks([query])[0]
        matches = self.store.collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where=validated_filter,
            include=["documents", "metadatas", "distances"],
        )
        return self._convert_results(
            ids=matches["ids"][0],
            documents=matches["documents"][0] or [],
            metadatas=matches["metadatas"][0] or [],
            distances=matches["distances"][0] or [],
            rank_field="semantic_rank",
        )

    # Search ChromaDB's normalized token metadata and rank candidates with BM25.
    def lexical_search(
        self,
        query: str,
        top_k: int = 5,
        metadata_filter: MetadataFilter | None = None,
    ) -> list[RetrievedChunk]:
        """Return lexical matches ranked by BM25 over the matching candidate pool."""
        self._validate_top_k(top_k)
        query_terms = self._query_terms(query)
        if not query_terms:
            return []
        validated_filter = self._validate_metadata_filter(metadata_filter)

        term_filters = [
            {"terms": {"$contains": term}}
            for term in query_terms
        ]
        lexical_filter: MetadataFilter
        if len(term_filters) == 1:
            lexical_filter = term_filters[0]
        else:
            lexical_filter = {"$or": term_filters}

        if validated_filter:
            collection_filter: MetadataFilter = {
                "$and": [validated_filter, lexical_filter]
            }
        else:
            collection_filter = lexical_filter

        matches = self.store.collection.get(
            where=collection_filter,
            limit=self.lexical_candidate_limit,
            include=["documents", "metadatas"],
        )
        candidate_documents = matches["documents"] or []
        candidate_metadatas = matches["metadatas"] or []
        candidates = self._convert_results(
            ids=matches["ids"],
            documents=candidate_documents,
            metadatas=candidate_metadatas,
            distances=[None] * len(candidate_documents),
        )
        ranked_candidates = self._rank_with_bm25(candidates, query_terms)
        return [
            RetrievedChunk(
                record_id=chunk.record_id,
                text=chunk.text,
                metadata=chunk.metadata,
                lexical_rank=rank,
            )
            for rank, chunk in enumerate(ranked_candidates[:top_k], start=1)
        ]

    # Combine semantic and BM25 rankings using reciprocal rank fusion.
    def hybrid_search(
        self,
        query: str,
        top_k: int = 5,
        metadata_filter: MetadataFilter | None = None,
        candidate_k: int | None = None,
    ) -> list[RetrievedChunk]:
        """Fuse independent vector and lexical result lists by reciprocal rank."""
        self._validate_top_k(top_k)
        if candidate_k is None:
            candidate_k = min(max(top_k * 4, 20), _MAX_TOP_K)
        self._validate_top_k(candidate_k)
        candidate_k = max(candidate_k, top_k)

        semantic_results = self.semantic_search(
            query,
            top_k=candidate_k,
            metadata_filter=metadata_filter,
        )
        lexical_results = self.lexical_search(
            query,
            top_k=min(max(top_k * 4, 20), _MAX_TOP_K),
            metadata_filter=metadata_filter,
        )
        fused: dict[str, RetrievedChunk] = {}

        for rank, chunk in enumerate(semantic_results, start=1):
            fused[chunk.record_id] = RetrievedChunk(
                record_id=chunk.record_id,
                text=chunk.text,
                metadata=chunk.metadata,
                distance=chunk.distance,
                semantic_rank=rank,
                fusion_score=1 / (self.rrf_constant + rank),
            )

        for rank, chunk in enumerate(lexical_results, start=1):
            previous = fused.get(chunk.record_id)
            if previous:
                fused[chunk.record_id] = RetrievedChunk(
                    record_id=previous.record_id,
                    text=previous.text,
                    metadata=previous.metadata,
                    distance=previous.distance,
                    semantic_rank=previous.semantic_rank,
                    lexical_rank=rank,
                    fusion_score=(
                        previous.fusion_score + 1 / (self.rrf_constant + rank)
                    ),
                )
            else:
                fused[chunk.record_id] = RetrievedChunk(
                    record_id=chunk.record_id,
                    text=chunk.text,
                    metadata=chunk.metadata,
                    lexical_rank=rank,
                    fusion_score=1 / (self.rrf_constant + rank),
                )

        ranked = sorted(
            fused.values(),
            key=lambda chunk: (-chunk.fusion_score, chunk.record_id),
        )
        return ranked[:top_k]

    # Route a retrieval request to the selected retrieval strategy.
    def retrieve(
        self,
        query: str,
        mode: RetrievalMode = "hybrid",
        top_k: int = 5,
        metadata_filter: MetadataFilter | None = None,
    ) -> list[RetrievedChunk]:
        """Run the requested retrieval mode and return ranked chunks."""
        if mode == "semantic":
            return self.semantic_search(query, top_k, metadata_filter)
        if mode == "lexical":
            return self.lexical_search(query, top_k, metadata_filter)
        if mode == "hybrid":
            return self.hybrid_search(query, top_k, metadata_filter)
        raise ValueError(f"Unsupported retrieval mode: {mode}")

    # Convert ChromaDB arrays into citation-ready chunks and clean metadata.
    def _convert_results(
        self,
        ids: list[str],
        documents: list[str | None],
        metadatas: list[dict[str, object] | None],
        distances: list[float | None],
        rank_field: Literal["semantic_rank"] | None = None,
    ) -> list[RetrievedChunk]:
        """Validate ChromaDB output and omit internal lexical terms from results."""
        if not (len(ids) == len(documents) == len(metadatas) == len(distances)):
            raise RuntimeError("ChromaDB returned result fields with different lengths.")

        results: list[RetrievedChunk] = []
        for rank, (record_id, text, metadata, distance) in enumerate(
            zip(ids, documents, metadatas, distances, strict=True),
            start=1,
        ):
            if text is None or metadata is None:
                raise RuntimeError("ChromaDB returned an incomplete search result.")
            if "source" not in metadata or "chunk_index" not in metadata:
                raise RuntimeError("A stored ChromaDB result is missing source metadata.")

            safe_metadata = {
                key: value
                for key, value in metadata.items()
                if key != "terms"
            }
            results.append(
                RetrievedChunk(
                    record_id=record_id,
                    text=text,
                    metadata=safe_metadata,
                    distance=float(distance) if distance is not None else None,
                    semantic_rank=rank if rank_field else None,
                    tokenized_terms=_TOKEN_PATTERN.findall(text.casefold()),
                )
            )
        return results

    # Rank lexical candidates using BM25 term frequency and inverse document frequency.
    def _rank_with_bm25(
        self,
        candidates: list[RetrievedChunk],
        query_terms: list[str],
    ) -> list[RetrievedChunk]:
        """Order candidate chunks by Okapi BM25 relevance to the query terms."""
        if not candidates:
            return []

        document_count = len(candidates)
        document_lengths = [len(chunk.tokenized_terms) for chunk in candidates]
        average_length = sum(document_lengths) / document_count or 1.0
        document_frequency = {
            term: sum(term in chunk.tokenized_terms for chunk in candidates)
            for term in set(query_terms)
        }
        k1 = 1.5
        b = 0.75

        def score(chunk: RetrievedChunk) -> float:
            """Calculate the candidate's BM25 score without using document text externally."""
            term_frequencies: dict[str, int] = {}
            for term in chunk.tokenized_terms:
                term_frequencies[term] = term_frequencies.get(term, 0) + 1

            total = 0.0
            length = len(chunk.tokenized_terms)
            for term in query_terms:
                frequency = term_frequencies.get(term, 0)
                if not frequency:
                    continue
                frequency_in_documents = document_frequency[term]
                inverse_frequency = math.log(
                    1
                    + (document_count - frequency_in_documents + 0.5)
                    / (frequency_in_documents + 0.5)
                )
                denominator = frequency + k1 * (
                    1 - b + b * length / average_length
                )
                total += inverse_frequency * (
                    frequency * (k1 + 1) / denominator
                )
            return total

        return sorted(
            candidates,
            key=lambda chunk: (-score(chunk), chunk.record_id),
        )

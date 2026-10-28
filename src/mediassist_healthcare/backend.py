"""Expose the MediAssist document, search, chat, and source APIs with FastAPI."""

from __future__ import annotations

import logging
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Literal
from zipfile import BadZipFile

from fastapi import FastAPI, File, Request, UploadFile
from pydantic import BaseModel, Field
from pypdf.errors import PdfReadError
from starlette.responses import JSONResponse

from mediassist_healthcare.embeddings import HuggingFaceEmbedder
from mediassist_healthcare.ingestion import load_document
from mediassist_healthcare.rag import RAGEngine, RAGGenerationError
from mediassist_healthcare.retriever import RetrievalMode, RetrievedChunk, Retriever
from mediassist_healthcare.settings import PROJECT_ROOT, get_embedding_model_name
from mediassist_healthcare.text_processing import chunk_by_paragraph
from mediassist_healthcare.vector_store import ChromaVectorStore

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DOCUMENT_EXTENSIONS = {".pdf", ".docx", ".txt"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_API_DATA_DIRECTORY = PROJECT_ROOT / "output" / "mediassist_api"
DEFAULT_UPLOAD_DIRECTORY = DEFAULT_API_DATA_DIRECTORY / "uploads"
DEFAULT_CATALOG_PATH = DEFAULT_API_DATA_DIRECTORY / "sources.sqlite3"
_LOGGER = logging.getLogger(__name__)


class APIInputError(ValueError):
    """Report a request that cannot be accepted by the local backend."""


class SourceNotFoundError(LookupError):
    """Report a source that is not present in the caller's session."""


class BackendProcessingError(RuntimeError):
    """Report a backend processing failure that the caller can retry."""


@dataclass(frozen=True)
class SourceRecord:
    """Describe a file stored for one frontend session."""

    file_id: str
    session_id: str
    name: str
    kind: Literal["document", "image"]
    size_bytes: int
    storage_path: str
    indexed_chunks: int
    created_at: str


class SourceResponse(BaseModel):
    """Return file details without exposing local filesystem paths."""

    file_id: str
    name: str
    kind: Literal["document", "image"]
    size_bytes: int
    indexed_chunks: int


class UploadResponse(SourceResponse):
    """Return source details and the upload result."""

    message: str


class CitationResponse(BaseModel):
    """Return safe source information for a grounded answer."""

    reference: str
    source: str
    chunk_number: int
    distance: float | None = None


class SearchRequest(BaseModel):
    """Describe one bounded semantic, lexical, or hybrid search request."""

    query: str = Field(min_length=1, max_length=4000)
    mode: RetrievalMode = "hybrid"
    top_k: int = Field(default=5, ge=1, le=100)


class ChatRequest(BaseModel):
    """Describe one user question for the RAG engine."""

    question: str = Field(min_length=1, max_length=4000)
    mode: RetrievalMode = "hybrid"
    top_k: int = Field(default=5, ge=1, le=100)


class SearchResult(BaseModel):
    """Return a retrieved chunk with a user-safe source label."""

    text: str
    source: str
    chunk_number: int
    distance: float | None = None
    fusion_score: float


class ChatResponse(BaseModel):
    """Return the RAG answer and its validated source citations."""

    answer: str
    status: Literal["answered", "out_of_scope", "insufficient_evidence"]
    citations: list[CitationResponse]
    retrieval_mode: RetrievalMode
    model: str


# Store the file catalog outside ChromaDB so images can also be listed/removed.
class SourceCatalog:
    """Persist session-owned upload metadata in a small local SQLite database."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    file_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL,
                    storage_path TEXT NOT NULL,
                    indexed_chunks INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS sources_session_idx "
                "ON sources (session_id, created_at)"
            )

    # Open a short-lived connection for an individual catalog operation.
    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    # Record one completed upload after storage and document indexing succeed.
    def add(self, source: SourceRecord) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sources (
                    file_id, session_id, name, kind, size_bytes, storage_path,
                    indexed_chunks, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    source.file_id,
                    source.session_id,
                    source.name,
                    source.kind,
                    source.size_bytes,
                    source.storage_path,
                    source.indexed_chunks,
                    source.created_at,
                ),
            )

    # Return catalog entries for one session in upload order.
    def list_for_session(self, session_id: str) -> list[SourceRecord]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sources WHERE session_id = ? "
                "ORDER BY created_at, file_id",
                (session_id,),
            ).fetchall()
        return [self._record_from_row(row) for row in rows]

    # Look up one source only when it belongs to the requesting session.
    def get_for_session(
        self,
        session_id: str,
        file_id: str,
    ) -> SourceRecord | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sources WHERE session_id = ? AND file_id = ?",
                (session_id, file_id),
            ).fetchone()
        return self._record_from_row(row) if row is not None else None

    # Remove catalog metadata after the source and its indexed chunks are removed.
    def remove(self, session_id: str, file_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM sources WHERE session_id = ? AND file_id = ?",
                (session_id, file_id),
            )

    # Convert a SQLite row to the immutable source record used by the API.
    @staticmethod
    def _record_from_row(row: sqlite3.Row) -> SourceRecord:
        return SourceRecord(
            file_id=row["file_id"],
            session_id=row["session_id"],
            name=row["name"],
            kind=row["kind"],
            size_bytes=row["size_bytes"],
            storage_path=row["storage_path"],
            indexed_chunks=row["indexed_chunks"],
            created_at=row["created_at"],
        )


class BackendService:
    """Coordinate uploads, local indexing, session filters, and RAG requests."""

    def __init__(
        self,
        upload_directory: Path = DEFAULT_UPLOAD_DIRECTORY,
        catalog_path: Path = DEFAULT_CATALOG_PATH,
        store: ChromaVectorStore | None = None,
        embedder: HuggingFaceEmbedder | None = None,
        retriever: Retriever | None = None,
        rag_engine: RAGEngine | None = None,
    ) -> None:
        """Create a service with lazy project components and injectable test doubles."""
        self.upload_directory = upload_directory
        self.catalog = SourceCatalog(catalog_path)
        self._store = store
        self._embedder = embedder
        self._retriever = retriever
        self._rag_engine = rag_engine

    # Validate session identifiers before using them in catalog filters or paths.
    @staticmethod
    def validate_session_id(session_id: str) -> str:
        """Return a canonical UUID string or reject an invalid session identifier."""
        try:
            return str(uuid.UUID(session_id))
        except ValueError as error:
            raise APIInputError("session_id must be a valid UUID.") from error

    # Ensure client-supplied file names cannot escape the generated storage folder.
    @staticmethod
    def _safe_filename(filename: str | None) -> str:
        if not filename or "\x00" in filename:
            raise APIInputError("A valid file name is required.")
        name = filename.replace("\\", "/").rsplit("/", maxsplit=1)[-1].strip()
        if not name or name in {".", ".."}:
            raise APIInputError("A valid file name is required.")
        return name

    # Confirm the file header matches the accepted extension for stored images.
    @staticmethod
    def _validate_image_signature(filename: str, content: bytes) -> None:
        suffix = Path(filename).suffix.casefold()
        signatures = {
            ".png": content.startswith(b"\x89PNG\r\n\x1a\n"),
            ".jpg": content.startswith(b"\xff\xd8\xff"),
            ".jpeg": content.startswith(b"\xff\xd8\xff"),
            ".webp": (
                len(content) >= 12
                and content.startswith(b"RIFF")
                and content[8:12] == b"WEBP"
            ),
        }
        if not signatures.get(suffix, False):
            raise APIInputError(
                f"The uploaded content does not match the {suffix[1:].upper()} image type."
            )

    # Validate a single upload and persist it under generated session/file IDs.
    async def upload(
        self,
        session_id: str,
        kind: Literal["document", "image"],
        upload: UploadFile,
    ) -> UploadResponse:
        """Store one file, indexing documents and retaining images for later use."""
        session_id = self.validate_session_id(session_id)
        name = self._safe_filename(upload.filename)
        suffix = Path(name).suffix.casefold()
        accepted_extensions = (
            DOCUMENT_EXTENSIONS if kind == "document" else IMAGE_EXTENSIONS
        )
        if suffix not in accepted_extensions:
            allowed = ", ".join(sorted(accepted_extensions))
            raise APIInputError(f"Unsupported {kind} type. Accepted: {allowed}.")

        content = await upload.read(MAX_UPLOAD_BYTES + 1)
        if not content:
            raise APIInputError("The uploaded file is empty.")
        if len(content) > MAX_UPLOAD_BYTES:
            raise APIInputError("The uploaded file exceeds the 20 MB limit.")
        if kind == "image":
            self._validate_image_signature(name, content)

        file_id = str(uuid.uuid4())
        file_directory = self.upload_directory / session_id / file_id
        file_directory.mkdir(parents=True, exist_ok=False)
        storage_path = file_directory / name
        storage_path.write_bytes(content)
        chunk_count = 0

        if kind == "document":
            chunk_count = self._index_document(
                storage_path,
                session_id=session_id,
                file_id=file_id,
                filename=name,
            )

        source = SourceRecord(
            file_id=file_id,
            session_id=session_id,
            name=name,
            kind=kind,
            size_bytes=len(content),
            storage_path=str(storage_path.resolve()),
            indexed_chunks=chunk_count,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self.catalog.add(source)
        return self._upload_response(source)

    # Extract, chunk, embed, and index one supported document for its session.
    def _index_document(
        self,
        source_path: Path,
        session_id: str,
        file_id: str,
        filename: str,
    ) -> int:
        try:
            document = load_document(source_path)
        except (
            BadZipFile,
            OSError,
            PdfReadError,
            ValueError,
            RuntimeError,
        ) as error:
            source_path.unlink(missing_ok=True)
            source_path.parent.rmdir()
            raise APIInputError(
                "Could not read the uploaded document. Confirm it is a valid "
                "PDF, DOCX, or UTF-8 TXT file."
            ) from error

        chunks = chunk_by_paragraph(document.text, max_chars=1000)
        if not chunks:
            source_path.unlink(missing_ok=True)
            source_path.parent.rmdir()
            raise APIInputError(
                "No selectable text was found. Scanned documents require OCR, "
                "which is not included in this phase."
            )

        try:
            vectors = self._get_embedder().embed_chunks(chunks)
            return self._get_store().index_chunks(
                chunks,
                vectors,
                source_path,
                document_metadata={
                    "session_id": session_id,
                    "upload_id": file_id,
                    "filename": filename,
                },
            )
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            source_path.unlink(missing_ok=True)
            source_path.parent.rmdir()
            raise BackendProcessingError(
                "Document indexing failed. Check embedding dependencies, model "
                "availability, and local ChromaDB storage."
            ) from error

    # List files owned by this session without revealing server paths.
    def list_sources(self, session_id: str) -> list[SourceResponse]:
        """Return the session's uploaded documents and images."""
        session_id = self.validate_session_id(session_id)
        return [
            self._source_response(source)
            for source in self.catalog.list_for_session(session_id)
        ]

    # Delete one session-owned upload and its indexed chunks, if any.
    def delete_source(self, session_id: str, file_id: str) -> None:
        """Delete the selected source file and its document vectors."""
        session_id = self.validate_session_id(session_id)
        try:
            file_id = str(uuid.UUID(file_id))
        except ValueError as error:
            raise APIInputError("file_id must be a valid UUID.") from error
        source = self.catalog.get_for_session(session_id, file_id)
        if source is None:
            raise SourceNotFoundError("The requested source was not found.")

        if source.kind == "document":
            try:
                self._get_store().collection.delete(
                    where={
                        "$and": [
                            {"session_id": session_id},
                            {"upload_id": file_id},
                        ]
                    }
                )
            except (OSError, RuntimeError, ValueError) as error:
                raise BackendProcessingError(
                    "The document's indexed chunks could not be deleted."
                ) from error

        file_directory = Path(source.storage_path).parent
        try:
            source_path = Path(source.storage_path)
            if source_path.is_file():
                source_path.unlink()
            file_directory.rmdir()
        except OSError as error:
            raise BackendProcessingError(
                "The uploaded file could not be removed from local storage."
            ) from error
        self.catalog.remove(session_id, file_id)

    # Return top-ranked retrieval results, constrained to one session's documents.
    def search(self, session_id: str, request: SearchRequest) -> list[SearchResult]:
        """Search only documents uploaded in the requested session."""
        session_id = self.validate_session_id(session_id)
        if not request.query.strip():
            raise APIInputError("The search query cannot be empty.")
        try:
            chunks = self._get_retriever().retrieve(
                request.query,
                mode=request.mode,
                top_k=request.top_k,
                metadata_filter={"session_id": session_id},
            )
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            raise BackendProcessingError(
                "Document retrieval failed. Check embedding dependencies, model "
                "availability, and local ChromaDB storage."
            ) from error
        return [self._search_result(chunk) for chunk in chunks]

    # Ask the RAG engine to answer using only this session's indexed documents.
    def chat(self, session_id: str, request: ChatRequest) -> ChatResponse:
        """Generate a scoped, evidence-grounded answer for one session."""
        session_id = self.validate_session_id(session_id)
        if not request.question.strip():
            raise APIInputError("The question cannot be empty.")
        try:
            response = self._get_rag_engine().ask(
                request.question,
                top_k=request.top_k,
                retrieval_mode=request.mode,
                metadata_filter={"session_id": session_id},
            )
        except RAGGenerationError as error:
            raise BackendProcessingError(
                "The RAG service could not complete this question. Check the "
                "OpenAI configuration and service connection."
            ) from error
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            raise BackendProcessingError(
                "The RAG service could not access its local model or vector store."
            ) from error

        source_names = {
            str(chunk.metadata.get("source", "")): str(
                chunk.metadata.get("filename")
                or Path(str(chunk.metadata.get("source", ""))).name
            )
            for chunk in response.retrieved_chunks
        }
        citations = [
            CitationResponse(
                reference=citation.reference,
                source=source_names.get(citation.source, Path(citation.source).name),
                chunk_number=citation.chunk_number,
                distance=citation.distance,
            )
            for citation in response.citations
        ]
        return ChatResponse(
            answer=response.answer,
            status=response.status,
            citations=citations,
            retrieval_mode=response.retrieval_mode,
            model=response.model,
        )

    # Build the default local vector store only when a document/search needs it.
    def _get_store(self) -> ChromaVectorStore:
        if self._store is None:
            self._store = ChromaVectorStore(
                embedding_model_name=get_embedding_model_name()
            )
        return self._store

    # Load the local embedding model only when a document/search needs it.
    def _get_embedder(self) -> HuggingFaceEmbedder:
        if self._embedder is None:
            self._embedder = HuggingFaceEmbedder(
                model_name=get_embedding_model_name()
            )
        return self._embedder

    # Reuse a single Retriever for the default store and embedding model.
    def _get_retriever(self) -> Retriever:
        if self._retriever is None:
            self._retriever = Retriever(
                self._get_store(),
                embedder=self._get_embedder(),
            )
        return self._retriever

    # Reuse the Phase 10 engine for API chat requests.
    def _get_rag_engine(self) -> RAGEngine:
        if self._rag_engine is None:
            self._rag_engine = RAGEngine(self._get_retriever())
        return self._rag_engine

    # Convert an internal source record to the public API response model.
    @staticmethod
    def _source_response(source: SourceRecord) -> SourceResponse:
        return SourceResponse(
            file_id=source.file_id,
            name=source.name,
            kind=source.kind,
            size_bytes=source.size_bytes,
            indexed_chunks=source.indexed_chunks,
        )

    # Add a concise outcome message to successful upload responses.
    @classmethod
    def _upload_response(cls, source: SourceRecord) -> UploadResponse:
        message = (
            f"Document uploaded and indexed into {source.indexed_chunks} chunks."
            if source.kind == "document"
            else "Image uploaded. OCR and image analysis are not enabled in Phase 12."
        )
        return UploadResponse(**cls._source_response(source).model_dump(), message=message)

    # Convert a retrieved chunk to a response that does not expose local paths.
    @staticmethod
    def _search_result(chunk: RetrievedChunk) -> SearchResult:
        source_path = str(chunk.metadata.get("source", ""))
        return SearchResult(
            text=chunk.text,
            source=str(chunk.metadata.get("filename") or Path(source_path).name),
            chunk_number=int(chunk.metadata.get("chunk_index", 0)) + 1,
            distance=chunk.distance,
            fusion_score=chunk.fusion_score,
        )


# Construct the HTTP application with injectable services for deterministic tests.
def create_app(service: BackendService | None = None) -> FastAPI:
    """Create the MediAssist API application and expose its health/upload/chat routes."""
    backend = service or BackendService()
    app = FastAPI(
        title="MediAssist Healthcare API",
        description=(
            "Local prototype APIs for document upload, session-scoped retrieval, "
            "and grounded chat. This service is not a production PHI boundary."
        ),
        version="0.1.0",
    )

    # Translate explicit service errors into stable API status codes.
    @app.exception_handler(APIInputError)
    async def handle_input_error(request: Request, error: APIInputError):
        _LOGGER.info("Rejected API request to %s: %s", request.url.path, error)
        return JSONResponse(
            status_code=422,
            content={"detail": str(error), "path": request.url.path},
        )

    @app.exception_handler(SourceNotFoundError)
    async def handle_missing_source(request: Request, error: SourceNotFoundError):
        _LOGGER.info("Source not found for API request to %s", request.url.path)
        return JSONResponse(
            status_code=404,
            content={"detail": str(error), "path": request.url.path},
        )

    @app.exception_handler(BackendProcessingError)
    async def handle_processing_error(request: Request, error: BackendProcessingError):
        _LOGGER.error("Backend processing failed for %s: %s", request.url.path, error)
        return JSONResponse(
            status_code=503,
            content={"detail": str(error), "path": request.url.path},
        )

    # Confirm that the HTTP process is running without requiring AI dependencies.
    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "mediassist-healthcare-api"}

    # Accept and index one PDF, DOCX, or TXT document.
    @app.post(
        "/api/sessions/{session_id}/documents",
        response_model=UploadResponse,
        status_code=201,
    )
    async def upload_document(
        session_id: str,
        file: UploadFile = File(...),
    ) -> UploadResponse:
        return await backend.upload(session_id, "document", file)

    # Accept one image and retain it for source management without OCR/vision.
    @app.post(
        "/api/sessions/{session_id}/images",
        response_model=UploadResponse,
        status_code=201,
    )
    async def upload_image(
        session_id: str,
        file: UploadFile = File(...),
    ) -> UploadResponse:
        return await backend.upload(session_id, "image", file)

    # Return the uploaded sources for the current browser session.
    @app.get(
        "/api/sessions/{session_id}/sources",
        response_model=list[SourceResponse],
    )
    def list_sources(session_id: str) -> list[SourceResponse]:
        return backend.list_sources(session_id)

    # Delete one session-owned upload and its vectors if it is a document.
    @app.delete("/api/sessions/{session_id}/sources/{file_id}", status_code=204)
    def delete_source(session_id: str, file_id: str) -> None:
        backend.delete_source(session_id, file_id)

    # Return retrieval candidates for development and evaluation workflows.
    @app.post(
        "/api/sessions/{session_id}/search",
        response_model=list[SearchResult],
    )
    def search(session_id: str, request: SearchRequest) -> list[SearchResult]:
        return backend.search(session_id, request)

    # Return an answer and its source citations for the current session.
    @app.post(
        "/api/sessions/{session_id}/chat",
        response_model=ChatResponse,
    )
    def chat(session_id: str, request: ChatRequest) -> ChatResponse:
        return backend.chat(session_id, request)

    app.state.backend_service = backend
    return app


app = create_app()


# Run the local API process using the standard Uvicorn development server.
def main() -> None:
    """Start the FastAPI backend on the local machine."""
    import uvicorn

    uvicorn.run(
        "mediassist_healthcare.backend:app",
        host="127.0.0.1",
        port=8000,
    )


if __name__ == "__main__":
    main()

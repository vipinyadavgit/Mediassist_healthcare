"""Expose the MediAssist document, search, chat, and source APIs with FastAPI."""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, Literal
from zipfile import BadZipFile

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from pypdf.errors import PdfReadError
from starlette.responses import JSONResponse

from mediassist_healthcare.auth import (
    AuthenticatedUser,
    AuthService,
    InvalidCredentialsError,
    LoginSession,
    UsernameTakenError,
)
from mediassist_healthcare.agent_Orchestration import AgentWorkflow
from mediassist_healthcare.embeddings import HuggingFaceEmbedder
from mediassist_healthcare.guardrails import (
    ConversationTurn,
    GuardrailViolation,
    MAX_IMAGES_PER_QUESTION,
)
from mediassist_healthcare.ingestion import load_document
from mediassist_healthcare.mcp_agent import MCPDataAgent
from mediassist_healthcare.multimodal_agent import ImageInput, MultimodalAgent
from mediassist_healthcare.observability import log_safe_event, safe_exception_fields
from mediassist_healthcare.planner_agent import PlannerAgent
from mediassist_healthcare.retriever import RetrievalMode, RetrievedChunk, Retriever
from mediassist_healthcare.reasoning_agent import ReasoningAgent
from mediassist_healthcare.retriever_agent import RetrieverAgent
from mediassist_healthcare.settings import PROJECT_ROOT, get_embedding_model_name
from mediassist_healthcare.text_processing import chunk_by_paragraph
from mediassist_healthcare.vector_store import ChromaVectorStore

MAX_UPLOAD_BYTES = 10_000_000
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


class SignupRequest(BaseModel):
    """Collect a single account's name, username, and password at signup."""

    first_name: str = Field(min_length=1, max_length=80)
    last_name: str = Field(min_length=1, max_length=80)
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=128)
    confirm_password: str = Field(min_length=1, max_length=128)


class LoginRequest(BaseModel):
    """Collect a username/password pair at login."""

    username: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class UserProfileResponse(BaseModel):
    """Expose account identity without password or credential-hash data."""

    user_id: str
    first_name: str
    last_name: str
    username: str


class AuthResponse(BaseModel):
    """Return a bearer session token and the authenticated user profile."""

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_at: float
    user: UserProfileResponse


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
    source_type: Literal["documents", "images", "mcp"] = "documents"
    distance: float | None = None


class SearchRequest(BaseModel):
    """Describe one bounded semantic, lexical, or hybrid search request."""

    query: str = Field(min_length=1, max_length=4000)
    mode: RetrievalMode = "hybrid"
    top_k: int = Field(default=5, ge=1, le=100)


class ChatRequest(BaseModel):
    """Describe one agent workflow request and its bounded optional context."""

    question: str = Field(min_length=1, max_length=4000)
    mode: RetrievalMode = "hybrid"
    top_k: int = Field(default=5, ge=1, le=100)
    image_source_ids: list[str] = Field(default_factory=list, max_length=5)
    history: list[dict[str, str]] = Field(default_factory=list, max_length=5)
    external_image_approved: bool = False


class TaskOutcomeResponse(BaseModel):
    """Return one planned task's completion status and reason."""

    task_id: str
    description: str
    source: Literal["documents", "images", "mcp"]
    status: Literal["completed", "incomplete"]
    reason: str


class WorkflowTraceResponse(BaseModel):
    """Expose a non-sensitive workflow node trace to the current UI session."""

    node: str
    status: Literal["completed", "failed"]
    duration_ms: int
    detail: str


class SearchResult(BaseModel):
    """Return a retrieved chunk with a user-safe source label."""

    text: str
    source: str
    chunk_number: int
    distance: float | None = None
    fusion_score: float


class ChatResponse(BaseModel):
    """Return the agent answer, task outcomes, and validated source citations."""

    answer: str
    status: Literal[
        "answered",
        "partial",
        "out_of_scope",
        "insufficient_evidence",
    ]
    citations: list[CitationResponse]
    retrieval_mode: RetrievalMode
    model: str
    intent: str = ""
    complexity: Literal["single_step", "multi_step"] = "single_step"
    tasks: list[TaskOutcomeResponse] = Field(default_factory=list)
    traces: list[WorkflowTraceResponse] = Field(default_factory=list)


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
    """Coordinate account-owned uploads, local retrieval, and agent workflows."""

    def __init__(
        self,
        upload_directory: Path = DEFAULT_UPLOAD_DIRECTORY,
        catalog_path: Path = DEFAULT_CATALOG_PATH,
        store: ChromaVectorStore | None = None,
        embedder: HuggingFaceEmbedder | None = None,
        retriever: Retriever | None = None,
        agent_workflow: AgentWorkflow | None = None,
    ) -> None:
        """Create a service with lazy project components and injectable test doubles."""
        self.upload_directory = upload_directory
        self.catalog = SourceCatalog(catalog_path)
        self.auth = AuthService(catalog_path)
        self._store = store
        self._embedder = embedder
        self._retriever = retriever
        self._agent_workflow = agent_workflow

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

    # Map validated image extensions to stable media types for the vision API.
    @staticmethod
    def _image_media_type(filename: str) -> str:
        media_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
        }
        media_type = media_types.get(Path(filename).suffix.casefold())
        if media_type is None:
            raise APIInputError("Choose a supported image file.")
        return media_type

    # Load only image records owned by this account and keep bytes in memory.
    def _load_selected_images(
        self,
        session_id: str,
        image_source_ids: list[str],
    ) -> list[ImageInput]:
        if len(image_source_ids) > MAX_IMAGES_PER_QUESTION:
            raise APIInputError(
                f"Use no more than {MAX_IMAGES_PER_QUESTION} images per question."
            )
        images: list[ImageInput] = []
        seen_ids: set[str] = set()
        for source_id in image_source_ids:
            try:
                normalized_id = str(uuid.UUID(source_id))
            except ValueError as error:
                raise APIInputError("An image source ID is invalid.") from error
            if normalized_id in seen_ids:
                continue
            seen_ids.add(normalized_id)
            source = self.catalog.get_for_session(session_id, normalized_id)
            if source is None or source.kind != "image":
                raise SourceNotFoundError("The requested image source was not found.")
            if source.size_bytes > MAX_UPLOAD_BYTES:
                raise APIInputError("The selected image exceeds the 10 MB limit.")
            storage_path = Path(source.storage_path).resolve()
            upload_root = (self.upload_directory / session_id).resolve()
            if not storage_path.is_relative_to(upload_root):
                raise SourceNotFoundError("The requested image source was not found.")
            try:
                content = storage_path.read_bytes()
            except OSError as error:
                raise BackendProcessingError(
                    "A selected image could not be read from local storage."
                ) from error
            if len(content) > MAX_UPLOAD_BYTES:
                raise APIInputError("The selected image exceeds the 10 MB limit.")
            self._validate_image_signature(source.name, content)
            images.append(
                ImageInput(
                    reference=f"I{len(images) + 1}",
                    name=source.name,
                    media_type=self._image_media_type(source.name),
                    content=content,
                )
            )
        return images

    # Validate direct chat image attachments without persisting them as account sources.
    async def read_chat_images(
        self,
        uploads: list[UploadFile],
    ) -> list[ImageInput]:
        """Read at most five supported, signature-checked image attachments."""
        if len(uploads) > MAX_IMAGES_PER_QUESTION:
            raise APIInputError(
                f"Attach no more than {MAX_IMAGES_PER_QUESTION} images per question."
            )
        images: list[ImageInput] = []
        for upload in uploads:
            name = self._safe_filename(upload.filename)
            if Path(name).suffix.casefold() not in IMAGE_EXTENSIONS:
                raise APIInputError(
                    "Chat attachments must be PNG, JPG, JPEG, or WEBP images."
                )
            content = await upload.read(MAX_UPLOAD_BYTES + 1)
            if not content:
                raise APIInputError("An attached image is empty.")
            if len(content) > MAX_UPLOAD_BYTES:
                raise APIInputError("An attached image exceeds the 10 MB limit.")
            self._validate_image_signature(name, content)
            images.append(
                ImageInput(
                    reference=f"I{len(images) + 1}",
                    name=name,
                    media_type=self._image_media_type(name),
                    content=content,
                )
            )
        return images

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
            raise APIInputError("The uploaded file exceeds the 10 MB limit.")
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

    # Run the multi-agent workflow using only this account's documents and images.
    def chat(
        self,
        session_id: str,
        request: ChatRequest,
        direct_images: list[ImageInput] | None = None,
    ) -> ChatResponse:
        """Plan, retrieve, analyze optional images, and verify response evidence."""
        session_id = self.validate_session_id(session_id)
        selected_images = self._load_selected_images(
            session_id,
            request.image_source_ids,
        )
        selected_images.extend(direct_images or [])
        if len(selected_images) > MAX_IMAGES_PER_QUESTION:
            raise APIInputError(
                f"Use no more than {MAX_IMAGES_PER_QUESTION} images per question."
            )
        selected_images = [
            ImageInput(
                reference=f"I{index}",
                name=image.name,
                media_type=image.media_type,
                content=image.content,
            )
            for index, image in enumerate(selected_images, start=1)
        ]
        history: list[ConversationTurn] = []
        for turn in request.history:
            question = turn.get("question", "")
            answer = turn.get("answer", "")
            if question and answer:
                history.append(ConversationTurn(question=question, answer=answer))
        try:
            response = self._get_agent_workflow().run(
                request.question,
                session_id=session_id,
                top_k=request.top_k,
                mode=request.mode,
                images=selected_images,
                history=history,
                external_image_approved=request.external_image_approved,
            )
        except GuardrailViolation as error:
            raise APIInputError(str(error)) from error
        except RuntimeError as error:
            log_safe_event(
                _LOGGER,
                "workflow.failed",
                **safe_exception_fields(error),
            )
            raise BackendProcessingError(
                "The agent workflow could not complete this question. Check the "
                "model configuration, local retrieval services, and provider connection."
            ) from error
        except (ImportError, OSError, ValueError) as error:
            log_safe_event(
                _LOGGER,
                "workflow.local_dependency_failed",
                **safe_exception_fields(error),
            )
            raise BackendProcessingError(
                "The agent workflow could not access its local model or vector store."
            ) from error

        citations = [
            CitationResponse(
                reference=citation.reference,
                source=citation.source,
                chunk_number=citation.chunk_number,
                source_type=citation.source_type,
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
            intent=response.intent,
            complexity=response.complexity,
            tasks=[
                TaskOutcomeResponse(
                    task_id=task.task_id,
                    description=task.description,
                    source=task.source,
                    status=task.status,
                    reason=task.reason,
                )
                for task in response.task_outcomes
            ],
            traces=[
                WorkflowTraceResponse(
                    node=trace.node,
                    status=trace.status,
                    duration_ms=trace.duration_ms,
                    detail=trace.detail,
                )
                for trace in response.traces
            ],
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

    # Build the lightweight requested-agent workflow without requiring LangGraph.
    def _get_agent_workflow(self) -> AgentWorkflow:
        if self._agent_workflow is None:
            self._agent_workflow = AgentWorkflow(
                planner=PlannerAgent(),
                retriever=RetrieverAgent(self._get_retriever()),
                multimodal=MultimodalAgent(),
                reasoner=ReasoningAgent(),
                mcp_data_agent=MCPDataAgent(),
            )
        return self._agent_workflow

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

    @app.middleware("http")
    async def observe_request(request: Request, call_next):
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception as error:
            route = getattr(request.scope.get("route"), "path", "/unmatched")
            log_safe_event(
                _LOGGER,
                "http.request_failed",
                request_id=request_id,
                method=request.method,
                route=route,
                **safe_exception_fields(error),
            )
            response = JSONResponse(
                status_code=500,
                content={
                    "detail": (
                        "An unexpected server error occurred. Please try again "
                        "or contact support with the request ID."
                    )
                },
            )

        route = getattr(request.scope.get("route"), "path", "/unmatched")
        duration_ms = max(0, round((time.perf_counter() - started) * 1000))
        log_safe_event(
            _LOGGER,
            "http.request_completed",
            request_id=request_id,
            method=request.method,
            route=route,
            http_status=response.status_code,
            duration_ms=duration_ms,
        )
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        return response
    bearer_scheme = HTTPBearer(auto_error=False)

    # Require a valid bearer session for every private API workflow.
    def require_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    ) -> AuthenticatedUser:
        if credentials is None or credentials.scheme.casefold() != "bearer":
            raise HTTPException(
                status_code=401,
                detail="Sign in to use this endpoint.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        user = backend.auth.authenticate(credentials.credentials)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="Your session is invalid or expired. Please sign in again.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return user

    # Bind the legacy session path segment to the authenticated account ID.
    def require_own_session(session_id: str, user: AuthenticatedUser) -> None:
        normalized_session_id = backend.validate_session_id(session_id)
        if normalized_session_id != user.user_id:
            raise SourceNotFoundError("The requested session was not found.")

    # Convert an issued login session to the public API response.
    def auth_response(session: LoginSession) -> AuthResponse:
        return AuthResponse(
            access_token=session.access_token,
            expires_at=session.expires_at,
            user=UserProfileResponse(
                user_id=session.user.user_id,
                first_name=session.user.first_name,
                last_name=session.user.last_name,
                username=session.user.username,
            ),
        )

    # Translate explicit service errors into stable API status codes.
    @app.exception_handler(APIInputError)
    async def handle_input_error(request: Request, error: APIInputError):
        log_safe_event(
            _LOGGER,
            "http.request_rejected",
            request_id=getattr(request.state, "request_id", ""),
            http_status=422,
        )
        return JSONResponse(
            status_code=422,
            content={"detail": str(error), "path": request.url.path},
        )

    @app.exception_handler(SourceNotFoundError)
    async def handle_missing_source(request: Request, error: SourceNotFoundError):
        log_safe_event(
            _LOGGER,
            "http.source_not_found",
            request_id=getattr(request.state, "request_id", ""),
            http_status=404,
        )
        return JSONResponse(
            status_code=404,
            content={"detail": str(error), "path": request.url.path},
        )

    @app.exception_handler(UsernameTakenError)
    async def handle_duplicate_username(request: Request, error: UsernameTakenError):
        log_safe_event(
            _LOGGER,
            "auth.signup_rejected",
            request_id=getattr(request.state, "request_id", ""),
            http_status=409,
        )
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(BackendProcessingError)
    async def handle_processing_error(request: Request, error: BackendProcessingError):
        log_safe_event(
            _LOGGER,
            "http.processing_failed",
            request_id=getattr(request.state, "request_id", ""),
            http_status=503,
        )
        return JSONResponse(
            status_code=503,
            content={"detail": str(error), "path": request.url.path},
        )

    # Confirm that the HTTP process is running without requiring AI dependencies.
    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "mediassist-healthcare-api"}

    # Create an account without issuing a bearer token; login is a separate step.
    @app.post("/api/auth/signup", response_model=UserProfileResponse, status_code=201)
    def signup(request: SignupRequest) -> UserProfileResponse:
        if request.password != request.confirm_password:
            raise APIInputError("Password and confirmation do not match.")
        try:
            user = backend.auth.signup(
                request.first_name,
                request.last_name,
                request.username,
                request.password,
            )
        except UsernameTakenError:
            raise
        except ValueError as error:
            raise APIInputError(str(error)) from error
        return UserProfileResponse(
            user_id=user.user_id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )

    # Verify a returning user's username and password and return a bearer token.
    @app.post("/api/auth/login", response_model=AuthResponse)
    def login(request: LoginRequest) -> AuthResponse:
        try:
            session = backend.auth.login(request.username, request.password)
        except InvalidCredentialsError as error:
            raise HTTPException(
                status_code=401,
                detail=str(error),
                headers={"WWW-Authenticate": "Bearer"},
            ) from error
        except ValueError as error:
            raise APIInputError(str(error)) from error
        return auth_response(session)

    # Return the current authenticated profile without exposing credential fields.
    @app.get("/api/auth/me", response_model=UserProfileResponse)
    def current_user(
        user: AuthenticatedUser = Depends(require_user),
    ) -> UserProfileResponse:
        return UserProfileResponse(
            user_id=user.user_id,
            first_name=user.first_name,
            last_name=user.last_name,
            username=user.username,
        )

    # Revoke the current bearer token at logout.
    @app.post("/api/auth/logout")
    def logout(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
        _user: AuthenticatedUser = Depends(require_user),
    ) -> dict[str, str]:
        if credentials is None:
            raise HTTPException(
                status_code=401,
                detail="Sign in to use this endpoint.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        backend.auth.logout(credentials.credentials)
        return {"status": "signed_out"}

    # Accept and index one PDF, DOCX, or TXT document.
    @app.post(
        "/api/sessions/{session_id}/documents",
        response_model=UploadResponse,
        status_code=201,
    )
    async def upload_document(
        session_id: str,
        file: UploadFile = File(...),
        user: AuthenticatedUser = Depends(require_user),
    ) -> UploadResponse:
        require_own_session(session_id, user)
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
        user: AuthenticatedUser = Depends(require_user),
    ) -> UploadResponse:
        require_own_session(session_id, user)
        return await backend.upload(session_id, "image", file)

    # Return the uploaded sources for the current browser session.
    @app.get(
        "/api/sessions/{session_id}/sources",
        response_model=list[SourceResponse],
    )
    def list_sources(
        session_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ) -> list[SourceResponse]:
        require_own_session(session_id, user)
        return backend.list_sources(session_id)

    # Delete one session-owned upload and its vectors if it is a document.
    @app.delete("/api/sessions/{session_id}/sources/{file_id}", status_code=204)
    def delete_source(
        session_id: str,
        file_id: str,
        user: AuthenticatedUser = Depends(require_user),
    ) -> None:
        require_own_session(session_id, user)
        backend.delete_source(session_id, file_id)

    # Return retrieval candidates for development and evaluation workflows.
    @app.post(
        "/api/sessions/{session_id}/search",
        response_model=list[SearchResult],
    )
    def search(
        session_id: str,
        request: SearchRequest,
        user: AuthenticatedUser = Depends(require_user),
    ) -> list[SearchResult]:
        require_own_session(session_id, user)
        return backend.search(session_id, request)

    # Return an answer and its source citations for the current session.
    @app.post(
        "/api/sessions/{session_id}/chat",
        response_model=ChatResponse,
    )
    def chat(
        session_id: str,
        request: ChatRequest,
        user: AuthenticatedUser = Depends(require_user),
    ) -> ChatResponse:
        require_own_session(session_id, user)
        return backend.chat(session_id, request)

    # Accept direct image attachments alongside selected stored image sources.
    @app.post(
        "/api/sessions/{session_id}/chat/with-images",
        response_model=ChatResponse,
    )
    async def chat_with_images(
        session_id: str,
        question: str = Form(..., min_length=1, max_length=4000),
        mode: RetrievalMode = Form("hybrid"),
        top_k: int = Form(5, ge=1, le=100),
        image_source_ids: str = Form("[]"),
        history: str = Form("[]"),
        external_image_approved: bool = Form(False),
        image_files: list[UploadFile] = File(default=[]),
        user: AuthenticatedUser = Depends(require_user),
    ) -> ChatResponse:
        require_own_session(session_id, user)
        try:
            selected_ids = json.loads(image_source_ids)
            conversation = json.loads(history)
        except json.JSONDecodeError as error:
            raise APIInputError(
                "Image source IDs and conversation history must be valid JSON."
            ) from error
        if not isinstance(selected_ids, list) or not all(
            isinstance(source_id, str) for source_id in selected_ids
        ):
            raise APIInputError("Image source IDs must be a JSON string array.")
        if not isinstance(conversation, list) or not all(
            isinstance(turn, dict) for turn in conversation
        ):
            raise APIInputError("Conversation history must be a JSON object array.")
        request = ChatRequest(
            question=question,
            mode=mode,
            top_k=top_k,
            image_source_ids=selected_ids,
            history=conversation,
            external_image_approved=external_image_approved,
        )
        direct_images = await backend.read_chat_images(image_files)
        return backend.chat(session_id, request, direct_images=direct_images)

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
        access_log=False,
    )


if __name__ == "__main__":
    main()

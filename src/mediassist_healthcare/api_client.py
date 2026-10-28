"""Provide typed Streamlit-side requests to the local MediAssist FastAPI."""

from __future__ import annotations

from typing import Any, Literal

import httpx


class APIClientError(RuntimeError):
    """Report a backend connection or request failure to the frontend."""


# Convert a response body or transport failure into a useful UI-facing error.
def _request_error(response: httpx.Response) -> APIClientError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    detail = body.get("detail") if isinstance(body, dict) else None
    message = str(detail or response.text or "The backend request failed.")
    return APIClientError(f"Backend returned HTTP {response.status_code}: {message}")


# Submit one user-selected file to the document or image endpoint.
def upload_source(
    base_url: str,
    session_id: str,
    kind: Literal["document", "image"],
    filename: str,
    content: bytes,
    content_type: str,
) -> dict[str, Any]:
    """Upload one file and return its public source record."""
    endpoint = "documents" if kind == "document" else "images"
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/api/sessions/{session_id}/{endpoint}",
            files={"file": (filename, content, content_type)},
            timeout=180.0,
        )
    except httpx.HTTPError as error:
        raise APIClientError(
            "Could not connect to the MediAssist API. Start the FastAPI backend "
            "and check MEDIASSIST_API_URL."
        ) from error
    if not response.is_success:
        raise _request_error(response)
    return response.json()


# Load persisted source names for the current browser session.
def list_sources(base_url: str, session_id: str) -> list[dict[str, Any]]:
    """Return all files previously added to the current backend session."""
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/api/sessions/{session_id}/sources",
            timeout=httpx.Timeout(
                timeout=2.0,
                connect=0.3,
                read=1.0,
                write=1.0,
                pool=1.0,
            ),
        )
    except httpx.HTTPError as error:
        raise APIClientError(
            "Could not connect to the MediAssist API. Start the FastAPI backend "
            "and check MEDIASSIST_API_URL."
        ) from error
    if not response.is_success:
        raise _request_error(response)
    return response.json()


# Remove a source from the backend and its document chunks from ChromaDB.
def delete_source(base_url: str, session_id: str, file_id: str) -> None:
    """Delete one uploaded source by its backend-generated identifier."""
    try:
        response = httpx.delete(
            f"{base_url.rstrip('/')}/api/sessions/{session_id}/sources/{file_id}",
            timeout=30.0,
        )
    except httpx.HTTPError as error:
        raise APIClientError(
            "Could not connect to the MediAssist API. Start the FastAPI backend "
            "and check MEDIASSIST_API_URL."
        ) from error
    if not response.is_success:
        raise _request_error(response)


# Ask the backend RAG engine and return its answer with source citations.
def ask_backend(
    base_url: str,
    session_id: str,
    question: str,
) -> dict[str, Any]:
    """Submit one question to session-scoped RAG and return the response."""
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/api/sessions/{session_id}/chat",
            json={"question": question, "mode": "hybrid", "top_k": 5},
            timeout=180.0,
        )
    except httpx.HTTPError as error:
        raise APIClientError(
            "Could not connect to the MediAssist API. Start the FastAPI backend "
            "and check MEDIASSIST_API_URL."
        ) from error
    if not response.is_success:
        raise _request_error(response)
    return response.json()

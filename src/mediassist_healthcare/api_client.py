"""Provide typed Streamlit-side requests to the local MediAssist FastAPI."""

from __future__ import annotations

import json
from typing import Any, Literal

import httpx


class APIClientError(RuntimeError):
    """Report a backend connection or request failure to the frontend."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.detail = detail or message


def _bearer_headers(access_token: str) -> dict[str, str]:
    """Build the authorization header used for a signed-in API request."""
    return {"Authorization": f"Bearer {access_token}"}


# Convert a response body or transport failure into a useful UI-facing error.
def _request_error(response: httpx.Response) -> APIClientError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    detail = body.get("detail") if isinstance(body, dict) else None
    safe_detail = (
        detail
        if isinstance(detail, str) and detail
        else "Please review the information and try again."
    )
    return APIClientError(
        f"Backend returned HTTP {response.status_code}: {safe_detail}",
        status_code=response.status_code,
        detail=safe_detail,
    )


def auth_error_message(
    error: APIClientError,
    action: Literal["login", "signup"],
) -> str:
    """Return a clear authentication error without exposing HTTP status codes."""
    if action == "login" and error.status_code == 401:
        return (
            "We couldn't sign you in with those credentials. Check your username "
            "and password, then try again."
        )
    if error.status_code is not None and error.status_code >= 500:
        return (
            "We couldn't complete your request right now. Please try again later."
        )
    return error.detail


# Create a user account and issue a signed-in API session.
def signup_user(
    base_url: str,
    first_name: str,
    last_name: str,
    username: str,
    password: str,
    confirm_password: str,
) -> dict[str, Any]:
    """Submit profile and password fields to the signup endpoint."""
    return _auth_request(
        base_url,
        "signup",
        {
            "first_name": first_name,
            "last_name": last_name,
            "username": username,
            "password": password,
            "confirm_password": confirm_password,
        },
    )


# Authenticate a returning user and issue a new API session.
def login_user(base_url: str, username: str, password: str) -> dict[str, Any]:
    """Submit credentials to the login endpoint."""
    return _auth_request(
        base_url,
        "login",
        {"username": username, "password": password},
    )


# Send a public signup/login request and expose backend failures to the UI.
def _auth_request(
    base_url: str,
    action: str,
    payload: dict[str, str],
) -> dict[str, Any]:
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/api/auth/{action}",
            json=payload,
            timeout=30.0,
        )
    except httpx.HTTPError as error:
        raise APIClientError(
            "Could not connect to the MediAssist API. Start the FastAPI backend "
            "and check MEDIASSIST_API_URL."
        ) from error
    if not response.is_success:
        raise _request_error(response)
    return response.json()


# Revoke the active API token when the user signs out.
def logout_user(base_url: str, access_token: str) -> None:
    """Revoke one authenticated API session."""
    try:
        response = httpx.post(
            f"{base_url.rstrip('/')}/api/auth/logout",
            headers=_bearer_headers(access_token),
            timeout=10.0,
        )
    except httpx.HTTPError as error:
        raise APIClientError(
            "Could not connect to the MediAssist API to end the session."
        ) from error
    if not response.is_success:
        raise _request_error(response)


# Submit one user-selected file to the document or image endpoint.
def upload_source(
    base_url: str,
    session_id: str,
    access_token: str,
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
            headers=_bearer_headers(access_token),
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
def list_sources(
    base_url: str,
    session_id: str,
    access_token: str,
) -> list[dict[str, Any]]:
    """Return all files previously added to the current backend session."""
    try:
        response = httpx.get(
            f"{base_url.rstrip('/')}/api/sessions/{session_id}/sources",
            headers=_bearer_headers(access_token),
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
def delete_source(
    base_url: str,
    session_id: str,
    access_token: str,
    file_id: str,
) -> None:
    """Delete one uploaded source by its backend-generated identifier."""
    try:
        response = httpx.delete(
            f"{base_url.rstrip('/')}/api/sessions/{session_id}/sources/{file_id}",
            headers=_bearer_headers(access_token),
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
    access_token: str,
    question: str,
    image_source_ids: list[str] | None = None,
    history: list[dict[str, str]] | None = None,
    image_files: list[tuple[str, bytes, str]] | None = None,
    external_image_approved: bool = False,
) -> dict[str, Any]:
    """Submit a bounded agent request with optional image and chat context."""
    payload = {
        "question": question,
        "mode": "hybrid",
        "top_k": 5,
        "image_source_ids": image_source_ids or [],
        "history": history or [],
        "external_image_approved": external_image_approved,
    }
    try:
        if image_files:
            response = httpx.post(
                f"{base_url.rstrip('/')}/api/sessions/{session_id}/chat/with-images",
                headers=_bearer_headers(access_token),
                data={
                    "question": question,
                    "mode": "hybrid",
                    "top_k": "5",
                    "image_source_ids": json.dumps(image_source_ids or []),
                    "history": json.dumps(history or []),
                    "external_image_approved": str(external_image_approved).lower(),
                },
                files=[
                    ("image_files", (name, content, content_type))
                    for name, content, content_type in image_files
                ],
                timeout=180.0,
            )
        else:
            response = httpx.post(
                f"{base_url.rstrip('/')}/api/sessions/{session_id}/chat",
                headers=_bearer_headers(access_token),
                json=payload,
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

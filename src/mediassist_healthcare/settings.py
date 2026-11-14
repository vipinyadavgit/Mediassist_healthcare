"""Load local project settings and secrets from the repository .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_OPENAI_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_OPENAI_VISION_MODEL = "gpt-4o-mini"
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"


class DatabaseConfigurationError(RuntimeError):
    """Report a missing or invalid read-only database configuration."""


# Load local settings and make OPENAI_KEY available under the SDK-standard name.
def load_environment(env_file: Path = ENV_FILE) -> None:
    """Load a chosen dotenv file without replacing variables already set by the OS."""
    load_dotenv(dotenv_path=env_file, override=False)

    openai_key = os.getenv("OPENAI_KEY")
    if openai_key and not os.getenv("OPENAI_API_KEY"):
        os.environ["OPENAI_API_KEY"] = openai_key


# Load the repository's .env settings when the application configuration is imported.
load_environment()


# Return the configured embedding model name, or the documented default.
def get_embedding_model_name() -> str:
    """Read the embedding model ID from the environment with a safe default."""
    return os.getenv("DEFAULT_MODEL_NAME", DEFAULT_EMBEDDING_MODEL)


# Return the configured OpenAI chat model, separate from the local embedding model.
def get_openai_chat_model_name() -> str:
    """Read the answer-generation model ID from the environment."""
    return os.getenv("OPENAI_CHAT_MODEL", DEFAULT_OPENAI_CHAT_MODEL)


# Return the configured model used to inspect image content.
def get_openai_vision_model_name() -> str:
    """Read the vision model ID from the environment."""
    return os.getenv("OPENAI_VISION_MODEL", DEFAULT_OPENAI_VISION_MODEL)


# Require an explicit server-side opt-in before sending image bytes to a provider.
def external_vision_is_enabled() -> bool:
    """Return whether external image processing has been explicitly approved."""
    return os.getenv("MEDIASSIST_ALLOW_EXTERNAL_VISION", "").strip().casefold() == "true"


# Require both an explicit opt-in and a LangSmith API key before external traces.
def langsmith_tracing_is_enabled() -> bool:
    """Return whether metadata-only LangSmith tracing is enabled by the operator."""
    return os.getenv("MEDIASSIST_ENABLE_LANGSMITH", "").strip().casefold() == "true"


# Keep LangSmith project selection separate from API credentials.
def get_langsmith_project_name() -> str:
    """Read the optional LangSmith project label with a stable local default."""
    return os.getenv("LANGSMITH_PROJECT", "mediassist-healthcare")


# Return the local FastAPI address used by the Streamlit frontend.
def get_api_base_url() -> str:
    """Read the backend URL from the environment with the local default."""
    return os.getenv("MEDIASSIST_API_URL", DEFAULT_API_BASE_URL).rstrip("/")


def get_mcp_database_environment() -> dict[str, str]:
    """Return validated connection settings for the read-only MCP process."""
    setting_names = {
        "MEDIASSIST_DB_HOST": "MEDIASSIST_DB_HOST",
        "MEDIASSIST_DB_PORT": "MEDIASSIST_DB_PORT",
        "MEDIASSIST_DB_NAME": "MEDIASSIST_DB_NAME",
        "MEDIASSIST_DB_USER": "MEDIASSIST_DB_USER",
        "MEDIASSIST_DB_PASSWORD": "MEDIASSIST_DB_PASSWORD",
    }
    missing = [
        environment_name
        for environment_name in setting_names.values()
        if not os.getenv(environment_name, "").strip()
    ]
    if missing:
        raise DatabaseConfigurationError(
            "Missing required read-only database settings: "
            + ", ".join(missing)
            + "."
        )

    environment = {
        environment_name: os.environ[environment_name].strip()
        for environment_name in setting_names.values()
    }
    try:
        port = int(environment["MEDIASSIST_DB_PORT"])
    except ValueError as error:
        raise DatabaseConfigurationError(
            "MEDIASSIST_DB_PORT must be a valid TCP port."
        ) from error
    if not 1 <= port <= 65535:
        raise DatabaseConfigurationError(
            "MEDIASSIST_DB_PORT must be between 1 and 65535."
        )
    sslmode = os.getenv("MEDIASSIST_DB_SSLMODE", "require").strip().casefold()
    if sslmode not in {"require", "verify-ca", "verify-full"}:
        raise DatabaseConfigurationError(
            "MEDIASSIST_DB_SSLMODE must require TLS "
            "(require, verify-ca, or verify-full)."
        )
    environment["MEDIASSIST_DB_PORT"] = str(port)
    environment["MEDIASSIST_DB_SSLMODE"] = sslmode
    sslrootcert = os.getenv("MEDIASSIST_DB_SSLROOTCERT", "").strip()
    if sslrootcert:
        environment["MEDIASSIST_DB_SSLROOTCERT"] = sslrootcert
    return environment

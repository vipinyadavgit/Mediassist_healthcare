"""Load local project settings and secrets from the repository .env file."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"
DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_OPENAI_CHAT_MODEL = "gpt-4o-mini"
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"


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


# Return the local FastAPI address used by the Streamlit frontend.
def get_api_base_url() -> str:
    """Read the backend URL from the environment with the local default."""
    return os.getenv("MEDIASSIST_API_URL", DEFAULT_API_BASE_URL).rstrip("/")

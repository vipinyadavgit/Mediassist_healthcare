"""Tests for loading local environment configuration safely."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mediassist_healthcare.settings import (
    DEFAULT_EMBEDDING_MODEL,
    get_embedding_model_name,
    load_environment,
)


class EnvironmentSettingsTests(unittest.TestCase):
    """Check .env loading, defaults, and preservation of existing environment values."""

    # Load model and API-key settings from a temporary dotenv file.
    def test_loads_model_and_openai_key(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "DEFAULT_MODEL_NAME=example/embedding-model\n"
                "OPENAI_KEY=test-key-not-a-real-credential\n",
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                load_environment(env_file)

                self.assertEqual(
                    get_embedding_model_name(),
                    "example/embedding-model",
                )
                self.assertEqual(
                    os.environ["OPENAI_API_KEY"],
                    "test-key-not-a-real-credential",
                )

    # Use the default embedding model when no model setting is present.
    def test_uses_default_model_when_setting_is_missing(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                get_embedding_model_name(),
                DEFAULT_EMBEDDING_MODEL,
            )

    # Preserve operating-system settings instead of replacing them from .env.
    def test_does_not_override_existing_environment_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "DEFAULT_MODEL_NAME=dotenv/model\n"
                "OPENAI_KEY=dotenv-key\n",
                encoding="utf-8",
            )

            with patch.dict(
                os.environ,
                {
                    "DEFAULT_MODEL_NAME": "system/model",
                    "OPENAI_API_KEY": "system-key",
                },
                clear=True,
            ):
                load_environment(env_file)

                self.assertEqual(get_embedding_model_name(), "system/model")
                self.assertEqual(os.environ["OPENAI_API_KEY"], "system-key")


if __name__ == "__main__":
    unittest.main()

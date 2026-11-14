"""Verify password hashing, signup/login, session expiry, and logout."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from mediassist_healthcare.auth import (
    AuthService,
    InvalidCredentialsError,
    UsernameTakenError,
)


class AuthServiceTests(unittest.TestCase):
    """Test account persistence and opaque bearer-session behavior."""

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "accounts.sqlite3"
        self.auth = AuthService(self.database_path)
        self.password = "Correct-Horse-Battery-42"
        self.created = self.auth.signup(
            "Alex",
            "Morgan",
            "Alex.M",
            self.password,
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_password_hash_is_stored_but_signup_does_not_issue_a_token(self) -> None:
        with closing(sqlite3.connect(self.database_path)) as connection:
            row = connection.execute(
                "SELECT username, password_hash FROM auth_users"
            ).fetchone()
            stored_token = connection.execute(
                "SELECT token_hash FROM auth_sessions"
            ).fetchone()

        self.assertEqual(row[0], "alex.m")
        self.assertTrue(row[1].startswith("pbkdf2_sha256$600000$"))
        self.assertNotIn(self.password, row[1])
        self.assertIsNone(stored_token)

        logged_in = self.auth.login("alex.m", self.password)
        with closing(sqlite3.connect(self.database_path)) as connection:
            stored_token = connection.execute(
                "SELECT token_hash FROM auth_sessions"
            ).fetchone()[0]
        self.assertNotEqual(stored_token, logged_in.access_token)

    def test_login_is_case_insensitive_and_returns_the_existing_account(self) -> None:
        logged_in = self.auth.login("ALEX.M", self.password)

        self.assertEqual(logged_in.user, self.created)
        self.assertIsNotNone(self.auth.authenticate(logged_in.access_token))

    def test_session_expires_after_30_minutes(self) -> None:
        now = 1_800_000_000.0
        with patch("mediassist_healthcare.auth.time.time", return_value=now):
            logged_in = self.auth.login("alex.m", self.password)

        self.assertEqual(logged_in.expires_at, now + 30 * 60)

    def test_duplicate_usernames_are_rejected_case_insensitively(self) -> None:
        with self.assertRaises(UsernameTakenError):
            self.auth.signup("Alex", "Other", "alex.m", self.password)

    def test_invalid_username_and_password_use_the_same_error(self) -> None:
        with self.assertRaisesRegex(
            InvalidCredentialsError,
            "Username or password is incorrect",
        ):
            self.auth.login("missing", self.password)
        with self.assertRaisesRegex(
            InvalidCredentialsError,
            "Username or password is incorrect",
        ):
            self.auth.login("alex.m", "wrong password value")

    def test_logout_revokes_the_token(self) -> None:
        logged_in = self.auth.login("alex.m", self.password)
        self.auth.logout(logged_in.access_token)

        self.assertIsNone(self.auth.authenticate(logged_in.access_token))

    def test_expired_session_is_rejected(self) -> None:
        logged_in = self.auth.login("alex.m", self.password)
        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.execute(
                "UPDATE auth_sessions SET expires_at = 0"
            )
            connection.commit()

        self.assertIsNone(self.auth.authenticate(logged_in.access_token))

    def test_example_password_meets_signup_policy(self) -> None:
        created = self.auth.signup("Casey", "Taylor", "casey.t", "Snooker@147")

        self.assertEqual(created.username, "casey.t")

    def test_signup_does_not_create_an_authenticated_session(self) -> None:
        created = self.auth.signup("Casey", "Taylor", "casey.t", "Snooker@147")

        with closing(sqlite3.connect(self.database_path)) as connection:
            sessions = connection.execute(
                "SELECT COUNT(*) FROM auth_sessions WHERE user_id = ?",
                (created.user_id,),
            ).fetchone()[0]

        self.assertEqual(sessions, 0)

    def test_rejects_passwords_outside_signup_policy(self) -> None:
        invalid_passwords = (
            ("short7", "at least 8 characters"),
            ("snooker@147", "start with an uppercase letter"),
            ("Snooker@xyz", "at least one number"),
            ("SNOOKER@147", "at least one lowercase letter"),
        )
        for password, expected_error in invalid_passwords:
            with self.subTest(password=password):
                with self.assertRaisesRegex(ValueError, expected_error):
                    self.auth.signup("Casey", "Taylor", "casey.t", password)

    def test_rejects_invalid_username(self) -> None:
        with self.assertRaisesRegex(ValueError, "Username must be"):
            self.auth.signup("Casey", "Taylor", "bad username", self.password)


if __name__ == "__main__":
    unittest.main()

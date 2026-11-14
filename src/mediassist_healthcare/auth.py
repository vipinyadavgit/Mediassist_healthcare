"""Store user accounts and expiring bearer sessions in the local SQLite database."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

_PASSWORD_HASH_ITERATIONS = 600_000
_PASSWORD_SALT_BYTES = 16
_PASSWORD_HASH_BYTES = 32
_SESSION_TOKEN_BYTES = 32
_SESSION_LIFETIME_SECONDS = 30 * 60
_USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{2,31}$")
_DUMMY_SALT = b"mediassist-login!"


class UsernameTakenError(ValueError):
    """Report that a signup username is already registered."""


class InvalidCredentialsError(ValueError):
    """Report an invalid username/password pair without identifying which failed."""


@dataclass(frozen=True)
class AuthenticatedUser:
    """Expose the safe profile data associated with a local account."""

    user_id: str
    first_name: str
    last_name: str
    username: str


@dataclass(frozen=True)
class LoginSession:
    """Return a raw bearer token once together with its authenticated user."""

    access_token: str
    expires_at: float
    user: AuthenticatedUser


def validate_password(password: str) -> None:
    """Enforce the password policy used by account creation."""
    if len(password) < 8:
        raise ValueError("Password must contain at least 8 characters.")
    if len(password) > 128:
        raise ValueError("Password cannot exceed 128 characters.")
    if not password[0].isupper():
        raise ValueError("Password must start with an uppercase letter.")
    if not any(character.islower() for character in password):
        raise ValueError("Password must include at least one lowercase letter.")
    if not any(character.isdigit() for character in password):
        raise ValueError("Password must include at least one number.")


class AuthService:
    """Create accounts, verify credentials, and manage expiring login sessions."""

    def __init__(self, database_path: str | Path) -> None:
        """Create the account tables in the local application SQLite database."""
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_users (
                    user_id TEXT PRIMARY KEY,
                    first_name TEXT NOT NULL,
                    last_name TEXT NOT NULL,
                    username TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    password_hash TEXT NOT NULL,
                    created_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS auth_sessions (
                    token_hash TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL REFERENCES auth_users(user_id)
                        ON DELETE CASCADE,
                    expires_at REAL NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS auth_sessions_user_idx "
                "ON auth_sessions (user_id)"
            )

    # Use short-lived SQLite connections and enforce user/session foreign keys.
    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        except Exception:
            connection.rollback()
            raise
        else:
            connection.commit()
        finally:
            connection.close()

    # Validate user-facing fields before hashing or writing account data.
    @staticmethod
    def _validate_profile(
        first_name: str,
        last_name: str,
        username: str,
        password: str,
    ) -> tuple[str, str, str]:
        first_name = first_name.strip()
        last_name = last_name.strip()
        username = username.strip().casefold()
        if not first_name or len(first_name) > 80:
            raise ValueError("First name must contain 1 to 80 characters.")
        if not last_name or len(last_name) > 80:
            raise ValueError("Last name must contain 1 to 80 characters.")
        if not _USERNAME_PATTERN.fullmatch(username):
            raise ValueError(
                "Username must be 3 to 32 characters and use letters, numbers, "
                "periods, underscores, or hyphens."
            )
        validate_password(password)
        return first_name, last_name, username

    # Derive a salted password hash suitable for storage instead of plaintext.
    @staticmethod
    def _hash_password(password: str, salt: bytes | None = None) -> str:
        salt = salt or secrets.token_bytes(_PASSWORD_SALT_BYTES)
        password_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            _PASSWORD_HASH_ITERATIONS,
            dklen=_PASSWORD_HASH_BYTES,
        )
        return "$".join(
            (
                "pbkdf2_sha256",
                str(_PASSWORD_HASH_ITERATIONS),
                salt.hex(),
                password_hash.hex(),
            )
        )

    # Compare a submitted password to an encoded hash without timing leaks.
    @staticmethod
    def _verify_password(password: str, encoded_hash: str) -> bool:
        try:
            algorithm, iterations_text, salt_hex, expected_hex = encoded_hash.split("$")
            iterations = int(iterations_text)
            salt = bytes.fromhex(salt_hex)
            expected_hash = bytes.fromhex(expected_hex)
        except (ValueError, TypeError):
            return False
        if algorithm != "pbkdf2_sha256" or iterations < 1:
            return False
        actual_hash = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt,
            iterations,
            dklen=len(expected_hash),
        )
        return hmac.compare_digest(actual_hash, expected_hash)

    # Register a unique local account without authenticating it.
    def signup(
        self,
        first_name: str,
        last_name: str,
        username: str,
        password: str,
    ) -> AuthenticatedUser:
        """Create an account; login is required before issuing a session."""
        first_name, last_name, username = self._validate_profile(
            first_name,
            last_name,
            username,
            password,
        )
        user = AuthenticatedUser(
            user_id=str(uuid.uuid4()),
            first_name=first_name,
            last_name=last_name,
            username=username,
        )
        password_hash = self._hash_password(password)
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO auth_users (
                        user_id, first_name, last_name, username,
                        password_hash, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user.user_id,
                        user.first_name,
                        user.last_name,
                        user.username,
                        password_hash,
                        time.time(),
                    ),
                )
        except sqlite3.IntegrityError as error:
            raise UsernameTakenError("That username is already registered.") from error
        return user

    # Verify a username/password pair and issue an opaque expiring bearer token.
    def login(self, username: str, password: str) -> LoginSession:
        """Authenticate an account using the same normalized username rules."""
        normalized_username = username.strip().casefold()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM auth_users WHERE username = ?",
                (normalized_username,),
            ).fetchone()

        if row is None:
            self._hash_password(password, salt=_DUMMY_SALT)
            raise InvalidCredentialsError("Username or password is incorrect.")
        if not self._verify_password(password, row["password_hash"]):
            raise InvalidCredentialsError("Username or password is incorrect.")

        user = self._user_from_row(row)
        return self._create_session(user)

    # Generate a random secret and persist only its SHA-256 digest.
    def _create_session(self, user: AuthenticatedUser) -> LoginSession:
        access_token = secrets.token_urlsafe(_SESSION_TOKEN_BYTES)
        expires_at = time.time() + _SESSION_LIFETIME_SECONDS
        token_hash = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE expires_at <= ?",
                (time.time(),),
            )
            connection.execute(
                "INSERT INTO auth_sessions (token_hash, user_id, expires_at) "
                "VALUES (?, ?, ?)",
                (token_hash, user.user_id, expires_at),
            )
        return LoginSession(
            access_token=access_token,
            expires_at=expires_at,
            user=user,
        )

    # Resolve a valid token to its user and reject expired or revoked sessions.
    def authenticate(self, access_token: str) -> AuthenticatedUser | None:
        """Return the account for an active session token, otherwise None."""
        token_hash = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT users.*
                FROM auth_sessions AS sessions
                JOIN auth_users AS users ON users.user_id = sessions.user_id
                WHERE sessions.token_hash = ? AND sessions.expires_at > ?
                """,
                (token_hash, time.time()),
            ).fetchone()
            if row is None:
                connection.execute(
                    "DELETE FROM auth_sessions WHERE token_hash = ? OR expires_at <= ?",
                    (token_hash, time.time()),
                )
                return None
        return self._user_from_row(row)

    # Revoke the current bearer token at logout without persisting its raw value.
    def logout(self, access_token: str) -> None:
        """Delete the session identified by the supplied access token."""
        token_hash = hashlib.sha256(access_token.encode("utf-8")).hexdigest()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM auth_sessions WHERE token_hash = ?",
                (token_hash,),
            )

    # Map a stored account row to the public profile model.
    @staticmethod
    def _user_from_row(row: sqlite3.Row) -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=row["user_id"],
            first_name=row["first_name"],
            last_name=row["last_name"],
            username=row["username"],
        )

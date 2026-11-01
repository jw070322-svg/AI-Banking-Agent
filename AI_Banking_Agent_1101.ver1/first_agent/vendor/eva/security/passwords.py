"""Password hashing for the development authentication provider.

This is deliberately standard-library PBKDF2-HMAC-SHA256, not a claim of a
production password system. Production deployments should delegate to the
organisation's identity provider (OIDC/SSO) or a reviewed password store.

Rules enforced here:
- plaintext passwords are never stored, returned, logged or put in a repr;
- every password gets a fresh random salt;
- verification uses `hmac.compare_digest`;
- unknown users still perform a dummy derivation to reduce a trivial timing
  oracle for username enumeration.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass

DEFAULT_ITERATIONS = 210_000
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_LENGTH = 1024


@dataclass(frozen=True)
class PasswordRecord:
    algorithm: str
    iterations: int
    salt_hex: str
    hash_hex: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "algorithm": self.algorithm,
            "iterations": self.iterations,
            "salt": self.salt_hex,
            "hash": self.hash_hex,
        }


def hash_password(
    password: str,
    *,
    iterations: int = DEFAULT_ITERATIONS,
    salt: bytes | None = None,
) -> PasswordRecord:
    if not isinstance(password, str):
        raise TypeError("password must be a string")
    if not (MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH):
        raise ValueError("password length is outside the allowed range")
    if iterations < 1:
        raise ValueError("iterations must be positive")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
        dklen=32,
    )
    return PasswordRecord(
        algorithm="pbkdf2_hmac_sha256",
        iterations=iterations,
        salt_hex=salt.hex(),
        hash_hex=digest.hex(),
    )


def verify_password(password: str, record: PasswordRecord) -> bool:
    if not isinstance(password, str) or not isinstance(record, PasswordRecord):
        return False
    if record.algorithm != "pbkdf2_hmac_sha256":
        return False
    try:
        salt = bytes.fromhex(record.salt_hex)
        expected = bytes.fromhex(record.hash_hex)
    except ValueError:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        record.iterations,
        dklen=len(expected),
    )
    return hmac.compare_digest(digest, expected)


def dummy_verify(password: str, *, iterations: int = DEFAULT_ITERATIONS) -> None:
    """Spend comparable work when a username does not exist.

    The result is discarded. The exact timing still differs slightly from a
    real record lookup, so this is mitigation, not a guarantee.
    """
    salt = b"module-8-dummy-salt"
    hashlib.pbkdf2_hmac(
        "sha256",
        (password or "").encode("utf-8"),
        salt,
        iterations,
        dklen=32,
    )

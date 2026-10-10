"""Password hashing and verification for admin login."""

from __future__ import annotations

import hashlib
import hmac
import secrets

from apofika import config


def hash_password(password: str, *, iterations: int = 390_000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algo, iterations_s, salt, digest = password_hash.split("$", 3)
    except ValueError:
        return False
    if algo != "pbkdf2_sha256":
        return False
    iterations = int(iterations_s)
    check = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return hmac.compare_digest(check, digest)


def configured_password_ok(password: str) -> bool:
    stored_hash = config.password_hash()
    if stored_hash:
        return verify_password(password, stored_hash)
    plain = config.password_plain()
    if plain is not None:
        return hmac.compare_digest(password, plain)
    # Dev fallback so local bootstrapping works before env is set.
    return hmac.compare_digest(password, "splitcasts")

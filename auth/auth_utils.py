"""
Utility functions for authentication and per‑user storage.

This module implements JSON Web Token (JWT) encoding and decoding
without external dependencies as well as helpers to normalise
user identifiers, compute password hashes and derive per‑user
storage locations.  It also exposes FastAPI dependency functions
for retrieving the current userid from the Authorization header
and optionally returning ``None`` when the header is missing.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import re
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


# ---------------------------------------------------------------------------
# JWT helpers (HS256)
#
# These functions provide a minimal implementation of JSON Web Tokens
# compatible with the HS256 algorithm.  They are deliberately
# dependency‑free so that the backend can run in constrained
# environments.  See RFC 7519 for details.

def _b64url_encode(raw: bytes) -> str:
    """Return a URL‑safe base64 encoded string without padding."""
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    """Decode a URL‑safe base64 encoded string adding padding if needed."""
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad)


def jwt_encode(payload: Dict[str, Any], secret: str) -> str:
    """Encode ``payload`` as a JWT signed with ``secret`` using HS256."""
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url_encode(
        json.dumps(header, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    sig_b64 = _b64url_encode(sig)
    return f"{header_b64}.{payload_b64}.{sig_b64}"


class JWTError(Exception):
    """Custom exception raised when JWT decoding fails."""
    pass


def jwt_decode(token: str, secret: str) -> Dict[str, Any]:
    """Decode and validate a JWT and return its payload.

    Raises ``JWTError`` if the token is malformed, the signature
    verification fails or the token has expired.
    """
    try:
        header_b64, payload_b64, sig_b64 = token.split(".")
    except ValueError:
        raise JWTError("Invalid token format")

    signing_input = f"{header_b64}.{payload_b64}".encode("utf-8")
    expected_sig = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url_encode(expected_sig), sig_b64):
        raise JWTError("Invalid token signature")

    try:
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
    except Exception:
        raise JWTError("Invalid token payload")

    # Check expiry
    exp = payload.get("exp")
    if exp is not None:
        try:
            exp_int = int(exp)
        except Exception:
            raise JWTError("Invalid exp")
        if int(time.time()) >= exp_int:
            raise JWTError("Token expired")

    return payload


# ---------------------------------------------------------------------------
# Configuration
#
# The secret key and token expiry can be configured via environment
# variables.  In development the default insecure secret is used so
# that the application can start without configuration.

SECRET_KEY = os.getenv("SECRET_KEY") or "CHANGE_ME_PLEASE_SET_SECRET_KEY"
TOKEN_EXPIRE_HOURS = int(os.getenv("TOKEN_EXPIRE_HOURS", "24"))


def require_secret() -> None:
    """Warn if SECRET_KEY is not set to a secure value."""
    if SECRET_KEY == "CHANGE_ME_PLEASE_SET_SECRET_KEY":
        # In development we merely warn; in production you should set
        # SECRET_KEY as an environment variable.  Logging via print
        # avoids dependency on logging configuration.
        print(
            "WARNING: SECRET_KEY is not set. Using an insecure default. "
            "Set SECRET_KEY in environment for production."
        )


def create_token(userid: str) -> str:
    """Create a new JWT for ``userid`` with configured expiry."""
    require_secret()
    payload = {
        "userid": userid,
        "exp": int(time.time()) + TOKEN_EXPIRE_HOURS * 3600,
    }
    return jwt_encode(payload, SECRET_KEY)


def utcnow_iso() -> str:
    """Return current UTC time in ISO 8601 format with 'Z' suffix."""
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def normalize_userid(value: Any) -> str:
    """Return a normalised userid stripped of whitespace and quotes."""
    if value is None:
        return ""
    if isinstance(value, str):
        v = value.strip()
        # remove surrounding quotes if present
        if (v.startswith("\"") and v.endswith("\"")) or (v.startswith("'") and v.endswith("'")):
            v = v[1:-1]
        return v.strip()
    return str(value).strip()


def password_hash(password: str, salt: str) -> str:
    """Return a SHA‑256 hash of ``salt:password``.  Matches original logic."""
    return hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()


def _safe_filename(s: str) -> str:
    """Sanitise a string for use as part of a filename (max 80 chars)."""
    s = (s or "").strip().replace(" ", "_")
    return re.sub(r"[^A-Za-z0-9_\-]", "_", s)[:80] or "client"


def user_root(userid: str) -> str:
    """Return the root directory for a given user within the data namespace."""
    # Use forward slashes; GitHub API expects paths using '/' not os.sep
    return f"data/users/{userid}"


def user_profile_path(userid: str) -> str:
    """Return the JSON path to a user's profile."""
    return f"{user_root(userid)}/profile.json"


def user_clients_dir(userid: str) -> str:
    """Return the directory under which client files are stored for a user."""
    return f"{user_root(userid)}/clients"


def user_client_file(userid: str, name: str, client_id: str) -> str:
    """Return a deterministic filename for a client given its name and id."""
    safe = _safe_filename(name)
    cid = (client_id or "").strip()
    return f"{user_clients_dir(userid)}/{safe}_{cid}.json"


# ---------------------------------------------------------------------------
# FastAPI dependencies
security = HTTPBearer(auto_error=False)


def get_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> str:
    """Return the userid from the Authorization header or raise 401.

    This dependency should be used on protected routes.  It validates
    the JWT and extracts the ``userid`` claim.  If the token is
    missing, invalid or expired an HTTP 401 will be raised.
    """
    require_secret()
    if credentials is None or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing token")
    try:
        payload = jwt_decode(credentials.credentials, SECRET_KEY)
        userid = (payload.get("userid") or "").strip()
        if not userid:
            raise HTTPException(status_code=401, detail="Invalid token")
        return userid
    except JWTError as exc:
        msg = str(exc) or "Invalid token"
        if "expired" in msg.lower():
            raise HTTPException(status_code=401, detail="Token expired")
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Optional[str]:
    """Like ``get_current_user`` but returns None if no token is present.

    When the Authorization header is missing this function returns
    ``None`` instead of raising.  This can be used for routes where
    authentication is optional.
    """
    if not credentials:
        return None
    token = (credentials.credentials or "").strip()
    if not token:
        return None
    try:
        payload = jwt_decode(token, SECRET_KEY)
        userid = (payload.get("userid") or "").strip()
        return userid or None
    except Exception:
        # If token provided but invalid treat as unauthorised
        raise HTTPException(status_code=401, detail="Invalid or expired token")

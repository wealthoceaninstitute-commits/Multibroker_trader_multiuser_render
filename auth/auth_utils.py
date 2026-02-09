import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple

from jose import jwt, JWTError
from passlib.context import CryptContext

from .github_store import GitHubStore

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _env(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    return v if v is not None else ""


def normalize_userid(userid: str) -> str:
    userid = (userid or "").strip()
    # allow letters, numbers, underscore, dash, dot (matches typical IDs)
    if not re.fullmatch(r"[A-Za-z0-9._-]{2,32}", userid):
        raise ValueError("Invalid userid. Use 2-32 chars: letters/numbers/._-")
    return userid


def get_users_root() -> str:
    # In your screenshot: data/users/<userid>/profile.json
    return _env("AUTH_USERS_ROOT", "data/users").strip("/")


def get_jwt_secret() -> str:
    sec = _env("JWT_SECRET", "CHANGE_ME")
    return sec


def get_token_ttl_minutes() -> int:
    try:
        return int(_env("JWT_TTL_MINUTES", "10080"))  # default 7 days
    except Exception:
        return 10080


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(userid: str, extra_claims: Optional[Dict[str, Any]] = None) -> str:
    ttl = timedelta(minutes=get_token_ttl_minutes())
    exp = datetime.now(timezone.utc) + ttl
    payload: Dict[str, Any] = {
        "sub": userid,
        "iat": int(datetime.now(timezone.utc).timestamp()),
        "exp": int(exp.timestamp()),
    }
    if extra_claims:
        payload.update(extra_claims)
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def decode_token(token: str) -> Dict[str, Any]:
    try:
        return jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
    except JWTError as e:
        raise ValueError("Invalid or expired token") from e


def profile_path(userid: str) -> str:
    root = get_users_root()
    return f"{root}/{userid}/profile.json"


def load_profile(store: GitHubStore, userid: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    return store.get_json(profile_path(userid))


def save_profile(store: GitHubStore, userid: str, profile: Dict[str, Any], sha: Optional[str], message: str):
    return store.put_json(profile_path(userid), profile, message=message, sha=sha)

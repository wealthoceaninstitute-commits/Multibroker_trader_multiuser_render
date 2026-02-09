from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, EmailStr, Field

from .auth_utils import (
    create_access_token,
    hash_password,
    load_profile,
    normalize_userid,
    now_utc_iso,
    save_profile,
    verify_password,
)
from .github_store import GitHubStore

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


class RegisterIn(BaseModel):
    userid: str = Field(..., min_length=2, max_length=32)
    email: EmailStr
    password: str = Field(..., min_length=4, max_length=128)


class LoginIn(BaseModel):
    userid: str = Field(..., min_length=2, max_length=32)
    password: str = Field(..., min_length=1, max_length=128)


def get_store() -> GitHubStore:
    return GitHubStore()


def require_user(creds: HTTPAuthorizationCredentials = Depends(bearer)) -> str:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing Authorization token")
    token = creds.credentials.strip()

    from .auth_utils import decode_token

    try:
        payload = decode_token(token)
        userid = normalize_userid(payload.get("sub") or "")
        return userid
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# ---- single-source handlers ----
def _register(payload: RegisterIn, store: GitHubStore):
    userid = normalize_userid(payload.userid)

    existing, _ = load_profile(store, userid)
    if existing is not None:
        raise HTTPException(status_code=409, detail="User ID already exists")

    created = now_utc_iso()
    profile = {
        "userid": userid,
        "email": str(payload.email),
        "password_hash": hash_password(payload.password),
        "created_at": created,
        "updated_at": created,
        "is_active": True,
    }

    save_profile(store, userid, profile, sha=None, message=f"register {userid}")

    token = create_access_token(userid, extra_claims={"email": str(payload.email)})
    return {"success": True, "userid": userid, "access_token": token, "token_type": "bearer"}


def _login(payload: LoginIn, store: GitHubStore):
    userid = normalize_userid(payload.userid)

    profile, sha = load_profile(store, userid)
    if profile is None or not profile.get("is_active", True):
        raise HTTPException(status_code=401, detail="Invalid userid or password")

    if not verify_password(payload.password, profile.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid userid or password")

    profile["updated_at"] = now_utc_iso()
    if sha:
        try:
            save_profile(store, userid, profile, sha=sha, message=f"login {userid}")
        except Exception:
            pass

    token = create_access_token(userid, extra_claims={"email": profile.get("email", "")})
    return {"success": True, "userid": userid, "access_token": token, "token_type": "bearer"}


def _me(userid: str, store: GitHubStore):
    profile, _ = load_profile(store, userid)
    if profile is None:
        raise HTTPException(status_code=401, detail="User not found")
    return {"success": True, "userid": userid, "email": profile.get("email", "")}


# ---- frontend legacy endpoints (NO frontend change needed) ----
@router.post("/register")
def register(payload: RegisterIn, store: GitHubStore = Depends(get_store)):
    return _register(payload, store)


@router.post("/login")
def login(payload: LoginIn, store: GitHubStore = Depends(get_store)):
    return _login(payload, store)


@router.get("/me")
def me(userid: str = Depends(require_user), store: GitHubStore = Depends(get_store)):
    return _me(userid, store)


# ---- optional aliases (/auth/*) without needing prefix in app ----
@router.post("/auth/register")
def register_auth(payload: RegisterIn, store: GitHubStore = Depends(get_store)):
    return _register(payload, store)


@router.post("/auth/login")
def login_auth(payload: LoginIn, store: GitHubStore = Depends(get_store)):
    return _login(payload, store)


@router.get("/auth/me")
def me_auth(userid: str = Depends(require_user), store: GitHubStore = Depends(get_store)):
    return _me(userid, store)

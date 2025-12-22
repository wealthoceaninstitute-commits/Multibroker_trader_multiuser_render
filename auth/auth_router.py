# auth/auth_router.py
from fastapi import APIRouter, Body, HTTPException
from datetime import datetime
from typing import Dict, Any

from .auth_utils import hash_password
from .github_store import (
    github_read_json,
    github_write_json,
    github_list_dir,
)

router = APIRouter(prefix="/auth", tags=["Auth"])

DATA_ROOT = "data/users"

def _safe(s: str) -> str:
    return "".join(c for c in (s or "").strip() if c.isalnum() or c in ("_", "-"))

@router.post("/register")
def register(payload: Dict[str, Any] = Body(...)):
    userid = _safe(payload.get("userid"))
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password")

    if not userid or not email or not password:
        raise HTTPException(400, "All fields required")

    # --- email uniqueness ---
    for u in github_list_dir(DATA_ROOT):
        if u.get("type") != "dir":
            continue
        prof = github_read_json(f"{DATA_ROOT}/{u['name']}/profile.json")
        if prof and prof.get("email") == email:
            raise HTTPException(400, "Email already registered")

    profile = {
        "userid": userid,
        "email": email,
        "password": hash_password(password),
        "role": "user",
        "status": "active",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    # --- save user ---
    github_write_json(f"{DATA_ROOT}/{userid}/profile.json", profile)

    # --- create structure ---
    github_write_json(f"{DATA_ROOT}/{userid}/clients/.keep", {})
    github_write_json(f"{DATA_ROOT}/{userid}/groups/.keep", {})
    github_write_json(f"{DATA_ROOT}/{userid}/copytrading/.keep", {})

    return {"success": True, "userid": userid}

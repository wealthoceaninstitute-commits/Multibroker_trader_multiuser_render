# auth/auth_router.py
from fastapi import APIRouter, HTTPException, Body
from datetime import datetime
from typing import Dict, Any

from .auth_utils import hash_password
from .github_store import github_write_json, github_list_dir, github_read_json

router = APIRouter(prefix="/auth", tags=["Auth"])

DATA_ROOT = "data/users"

def _safe(s: str) -> str:
    return "".join(c for c in (s or "").strip() if c.isalnum() or c in ("_","-"))

@router.post("/register")
def register(payload: Dict[str, Any] = Body(...)):
    userid = _safe(payload.get("userid"))
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""

    if not userid or not email or not password:
        raise HTTPException(status_code=400, detail="All fields required")

    # Check email uniqueness
    users = github_list_dir(DATA_ROOT)
    for u in users:
        if u.get("type") != "dir":
            continue
        prof = github_read_json(f"{DATA_ROOT}/{u['name']}/profile.json")
        if prof and prof.get("email") == email:
            raise HTTPException(status_code=400, detail="Email already exists")

    profile = {
        "userid": userid,
        "email": email,
        "password": hash_password(password),
        "created_at": datetime.utcnow().isoformat() + "Z",
        "status": "active"
    }

    # Save profile
    github_write_json(
        f"{DATA_ROOT}/{userid}/profile.json",
        profile
    )

    # Create empty folders
    github_write_json(f"{DATA_ROOT}/{userid}/clients/.keep", {"_": True})
    github_write_json(f"{DATA_ROOT}/{userid}/groups/.keep", {"_": True})
    github_write_json(f"{DATA_ROOT}/{userid}/copytrading/.keep", {"_": True})

    return {"success": True, "userid": userid}

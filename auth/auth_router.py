
import os, json
from datetime import datetime
from fastapi import APIRouter, HTTPException, Body, Header
from typing import Dict, Any

from .auth_utils import hash_password, verify_password, create_token, decode_token
from .github_store import github_read_json, github_write_json, github_list_dir

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

    # email uniqueness
    users = github_list_dir(DATA_ROOT)
    for u in users:
        if u.get("type") != "dir":
            continue
        prof = github_read_json(f"{DATA_ROOT}/{u['name']}/profile.json")
        if prof and prof.get("email") == email:
            raise HTTPException(status_code=400, detail="Email already registered")

    profile = {
        "userid": userid,
        "email": email,
        "password": hash_password(password),
        "role": "user",
        "status": "active",
        "created_at": datetime.utcnow().isoformat() + "Z",
    }

    github_write_json(f"{DATA_ROOT}/{userid}/profile.json", profile)
    # create empty folders by writing .keep files
    github_write_json(f"{DATA_ROOT}/{userid}/clients/.keep", {"_": True})
    github_write_json(f"{DATA_ROOT}/{userid}/groups/.keep", {"_": True})
    github_write_json(f"{DATA_ROOT}/{userid}/copytrading/.keep", {"_": True})

    return {"success": True, "userid": userid}

@router.post("/login")
def login(payload: Dict[str, Any] = Body(...)):
    userid = _safe(payload.get("userid"))
    password = payload.get("password") or ""

    prof = github_read_json(f"{DATA_ROOT}/{userid}/profile.json")
    if not prof or not verify_password(password, prof.get("password","")):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token({"userid": userid, "role": prof.get("role","user")})
    return {"token": token, "userid": userid}

def get_current_user(authorization: str = Header(...)) -> str:
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid auth header")
    token = authorization.replace("Bearer ","")
    return decode_token(token)["userid"]

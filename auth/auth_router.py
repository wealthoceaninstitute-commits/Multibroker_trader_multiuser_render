from fastapi import APIRouter, Body, HTTPException
from datetime import datetime
from typing import Dict, Any
import hashlib

from .github_store import github_write_json

router = APIRouter(prefix="/auth", tags=["Auth"])

def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

@router.post("/register")
def register(payload: Dict[str, Any] = Body(...)):
    userid = payload.get("userid")
    email = payload.get("email")
    password = payload.get("password")

    if not userid or not email or not password:
        raise HTTPException(status_code=400, detail="All fields required")

    profile = {
        "userid": userid,
        "email": email,
        "password": hash_password(password),
        "created_at": datetime.utcnow().isoformat()
    }

    github_write_json(
        f"data/users/{userid}/profile.json",
        profile
    )

    return {"success": True}

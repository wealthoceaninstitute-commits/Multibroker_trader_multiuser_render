from fastapi import APIRouter, Body, HTTPException
from datetime import datetime
from typing import Dict, Any
import hashlib, json, os
import requests
from fastapi import Body

from .github_store import github_write_json

router = APIRouter(prefix="/auth", tags=["Auth"])

def hash_password(p: str) -> str:
    return hashlib.sha256(p.encode()).hexdigest()

@router.post("/register")
def register(payload: Dict[str, Any] = Body(...)):
    """
    Register a new user.

    Expects a JSON body with `userid`, `email` and `password`.  All
    three fields are required.  The password is hashed before
    persistence.  User profiles are stored on GitHub via
    `github_write_json`.  Any failure to write to GitHub is logged
    but does not prevent user creation.
    """
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
    # Attempt to write to GitHub but do not crash on failure
    try:
        github_write_json(
            f"data/users/{userid}/profile.json",
            profile
        )
    except Exception as e:
        # Log the error.  In production you might send this to a logger


        print("[auth] GitHub write failed:", e)
    return {"success": True}


GITHUB_OWNER = os.getenv("GITHUB_REPO_OWNER", "wealthoceaninstitute-commits")
GITHUB_REPO  = os.getenv("GITHUB_REPO_NAME", "Multiuser_clients")
BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")


@router.post("/login")
def login(payload: Dict[str, Any] = Body(...)):
    username = payload.get("username")
    password = payload.get("password")

    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")

    path = f"data/users/{username}/profile.json"
    url = f"https://raw.githubusercontent.com/{GITHUB_OWNER}/{GITHUB_REPO}/{BRANCH}/{path}"

    r = requests.get(url, timeout=10)
    if r.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid login")

    user = r.json()
    if user["password"] != hash_pwd(password):
        raise HTTPException(status_code=401, detail="Invalid login")

    return {
        "success": True,
        "userid": username
    }

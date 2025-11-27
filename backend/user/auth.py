# backend/user/auth.py

import os
import json
import hashlib
import secrets
from fastapi import APIRouter, HTTPException, Depends, Header
from typing import Optional

from backend.user.storage import (
    create_user_folders,
    save_user_credentials,
    load_user_credentials,
)

router = APIRouter()

# In-memory session store (We can later replace with Redis)
ACTIVE_SESSIONS = {}   # token -> username


# -------------------------------
# PASSWORD HASHING
# -------------------------------

def hash_password(password: str) -> str:
    """Hashes password with SHA256."""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str, hashed: str) -> bool:
    return hash_password(password) == hashed


# -------------------------------
# USER SIGNUP
# -------------------------------

@router.post("/signup")
def signup(username: str, password: str):
    """
    Register a new user.
    Creates:
      users/<username>/
      users/<username>/user.json
      users/<username>/clients/{dhan,motilal}/
    """

    username = username.lower().strip()

    # Check if already exists
    if load_user_credentials(username) is not None:
        raise HTTPException(status_code=400, detail="User already exists")

    hashed = hash_password(password)

    # Create folder structure & save user.json
    create_user_folders(username)
    save_user_credentials(username, {"username": username, "password": hashed})

    return {"status": "success", "message": "User created successfully"}


# -------------------------------
# USER LOGIN
# -------------------------------

@router.post("/login")
def login(username: str, password: str):
    username = username.lower().strip()

    creds = load_user_credentials(username)
    if creds is None:
        raise HTTPException(status_code=400, detail="User not found")

    if not verify_password(password, creds["password"]):
        raise HTTPException(status_code=401, detail="Incorrect password")

    # Generate session token
    token = secrets.token_hex(32)
    ACTIVE_SESSIONS[token] = username

    return {
        "status": "success",
        "token": token,
        "username": username
    }


# -------------------------------
# AUTHENTICATION DEPENDENCY
# -------------------------------

def get_current_user(x_auth_token: Optional[str] = Header(None)):
    """
    Reads 'x-auth-token' from headers and validates the session.
    """

    if not x_auth_token:
        raise HTTPException(status_code=401, detail="Missing auth token")

    if x_auth_token not in ACTIVE_SESSIONS:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return ACTIVE_SESSIONS[x_auth_token]


# -------------------------------
# WHOAMI (optional)
# -------------------------------

@router.get("/whoami")
def whoami(username: str = Depends(get_current_user)):
    return {"logged_in_as": username}

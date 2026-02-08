"""
FastAPI router providing user registration, login and account endpoints.

This module defines a router which can be included into the main
FastAPI application to add authentication functionality.  It
persists user profiles in a GitHub repository (if configured) and
issues JWT access tokens on successful login.

Example::

    from fastapi import FastAPI
    from auth.auth_router import router as auth_router

    app = FastAPI()
    app.include_router(auth_router, prefix="/auth")
"""

from __future__ import annotations

import base64
import os
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from . import auth_utils
from .auth_utils import (
    normalize_userid,
    password_hash,
    create_token,
    get_current_user,
    get_current_user_optional,
    utcnow_iso,
    user_profile_path,
)
from .github_store import gh_get_json, gh_put_json


router = APIRouter()


@router.get("/")
def root():
    """Health endpoint for the auth router."""
    return {"ok": True, "module": "auth"}


@router.post("/register")
def auth_register(payload: Dict[str, Any] = Body(...)):
    """
    Register a new user.

    Expects a JSON object with keys ``userid``, ``email`` and
    ``password``.  An optional ``confirm_password`` may be supplied
    and will be checked for equality with ``password``.  If the
    userid already exists an error is returned.
    """
    userid = normalize_userid(payload.get("userid"))
    email = (payload.get("email") or "").strip()
    password = (payload.get("password") or "").strip()
    confirm = (payload.get("confirm_password") or payload.get("confirmPassword") or "").strip()

    if not userid or not email or not password:
        return {"success": False, "error": "Missing userid/email/password"}
    if confirm and password != confirm:
        return {"success": False, "error": "Passwords do not match"}

    existing, _ = gh_get_json(user_profile_path(userid))
    if existing:
        return {"success": False, "error": "User already exists"}

    # Generate salt and hash the password
    salt = base64.b64encode(os.urandom(12)).decode("utf-8")
    profile = {
        "userid": userid,
        "email": email,
        "salt": salt,
        "password_hash": password_hash(password, salt),
        "created_at": utcnow_iso(),
        "updated_at": utcnow_iso(),
    }
    gh_put_json(user_profile_path(userid), profile, message=f"register {userid}")
    return {"success": True, "userid": userid}


@router.post("/login")
def auth_login(payload: Dict[str, Any] = Body(...)):
    """
    Authenticate a user and return an access token.

    Expects ``userid`` and ``password`` in the request body.  If
    authentication succeeds returns a JSON object with ``success``,
    ``userid`` and ``access_token``.
    """
    userid = normalize_userid(payload.get("userid"))
    password = (payload.get("password") or "").strip()

    if not userid or not password:
        return {"success": False}

    profile, _ = gh_get_json(user_profile_path(userid))
    if not profile or not isinstance(profile, dict):
        return {"success": False}

    salt = profile.get("salt", "")
    ph = profile.get("password_hash", "")
    if not salt or not ph:
        return {"success": False}

    if password_hash(password, salt) != ph:
        return {"success": False}

    token = create_token(userid)
    return {"success": True, "userid": userid, "access_token": token}


@router.get("/me")
def me(userid: str = Depends(get_current_user)):
    """Return the userid of the currently authenticated user."""
    return {"success": True, "userid": userid}


# Note: APIRouter does not support a per‑router exception_handler decorator.
# The main FastAPI application defines its own HTTPException handler.
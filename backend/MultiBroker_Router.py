# MultiBroker_Router.py
import os, json, importlib, base64
from typing import Any, Dict, List, Optional
import hashlib
import secrets
from datetime import datetime, timedelta
from fastapi import FastAPI, Body, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from collections import OrderedDict
import importlib, os, time
import threading
import os, sqlite3, threading, requests
from fastapi import Query
import pandas as pd


STAT_KEYS = ["pending", "traded", "rejected", "cancelled", "others"]
summary_data_global: Dict[str, Dict[str, Any]] = {}
SYMBOL_DB_PATH = os.path.join(os.path.abspath(os.environ.get("DATA_DIR", "./data")), "symbols.db")
SYMBOL_TABLE   = "symbols"
SYMBOL_CSV_URL = "https://raw.githubusercontent.com/Pramod541988/Stock_List/main/security_id.csv"
_symbol_db_lock = threading.Lock()


# --- GitHub global config (single source of truth) ---
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN")                       # <-- set in Railway
GITHUB_OWNER  = os.getenv("GITHUB_REPO_OWNER") or "wealthoceaninstitute-commits"
GITHUB_REPO   = os.getenv("GITHUB_REPO_NAME")  or "Clients"
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")




# =============================================================
#                MULTI-USER ACCOUNT SYSTEM
# =============================================================
import os, json, hashlib, secrets, base64
from datetime import datetime, timedelta
from fastapi import HTTPException, Header

# ---------------- Configuration ----------------
BASE_DIR = os.path.abspath(os.environ.get("DATA_DIR", "./data"))
USERS_ROOT = os.path.join(BASE_DIR, "users")
os.makedirs(USERS_ROOT, exist_ok=True)

GITHUB_REPO = os.environ.get("GITHUB_REPO", "wealthoceaninstitute-commits/Clients")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

PASSWORD_SALT = os.environ.get("USER_PASSWORD_SALT", "woi_default_salt")
SESSION_TTL_MIN = int(os.environ.get("USER_SESSION_TTL", "720"))  # 12 hours

_user_sessions = {}   # token → { username, expires_at }


# ---------------- Safe helpers ----------------
def _safe(s: str) -> str:
    return "".join(c for c in (s or "") if c.isalnum() or c in ("_", "-")).strip()


def _user_dir(username: str) -> str:
    return os.path.join(USERS_ROOT, _safe(username))


def _user_json_path(username: str) -> str:
    return os.path.join(_user_dir(username), "user.json")


# ---------------- Password hashing ----------------
def _hash_password(raw: str) -> str:
    raw = (raw or "").strip()
    return hashlib.sha256((raw + PASSWORD_SALT).encode()).hexdigest()


# ---------------- Session creation ----------------
def _create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    _user_sessions[token] = {
        "username": username,
        "expires_at": datetime.utcnow() + timedelta(minutes=SESSION_TTL_MIN)
    }
    return token


def get_current_user(x_auth_token: str = Header(None)):
    if not x_auth_token or x_auth_token not in _user_sessions:
        raise HTTPException(401, "Not authenticated")

    sess = _user_sessions[x_auth_token]
    if datetime.utcnow() > sess["expires_at"]:
        _user_sessions.pop(x_auth_token, None)
        raise HTTPException(401, "Session expired")

    return sess["username"]


# ---------------- GitHub folder creator ----------------
def _github_headers():
    h = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h


def _github_api(url: str):
    return f"https://api.github.com/repos/{GITHUB_REPO}/{url}"


def _github_write(path: str, content: str, message: str):
    if not GITHUB_TOKEN:
        return  # silent local-only mode

    url = _github_api(f"contents/{path}")

    # check if exists
    r = requests.get(url, headers=_github_headers())
    sha = r.json().get("sha") if r.status_code == 200 else None

    payload = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": GITHUB_BRANCH
    }
    if sha:
        payload["sha"] = sha

    requests.put(url, headers=_github_headers(), json=payload)


def _ensure_github_user(username: str):
    base = f"users/{_safe(username)}"
    # create .keep files
    _github_write(f"{base}/.keep", "", "create user folder")
    _github_write(f"{base}/clients/dhan/.keep", "", "create dhan folder")
    _github_write(f"{base}/clients/motilal/.keep", "", "create motilal folder")


# ---------------- USER CREATION ----------------
def register_user(username: str, password: str, email: str):
    username = _safe(username)
    path = _user_json_path(username)

    if os.path.exists(path):
        raise HTTPException(400, "User already exists")

    os.makedirs(os.path.dirname(path), exist_ok=True)

    doc = {
        "username": username,
        "email": email,
        "password_hash": _hash_password(password),
        "created_at": datetime.utcnow().isoformat() + "Z"
    }

    with open(path, "w") as f:
        json.dump(doc, f, indent=2)

    # also create folder in GitHub
    _ensure_github_user(username)
    _github_write(f"users/{username}/user.json",
                  json.dumps(doc, indent=2),
                  f"create user {username}")

    return doc


# ---------------- USER LOGIN ----------------
def login_user(username: str, password: str):
    path = _user_json_path(username)
    if not os.path.exists(path):
        raise HTTPException(400, "User not found")

    doc = json.load(open(path))

    if doc["password_hash"] != _hash_password(password):
        raise HTTPException(400, "Invalid password")

    token = _create_session(username)
    return {"token": token, "username": username}


# =============================================================
#                  USER ROUTES (Frontend Login Page)
# =============================================================

@app.post("/users/register")
def api_user_register(payload: dict = Body(...)):
    username = payload.get("username", "").strip()
    password = payload.get("password", "").strip()
    email    = payload.get("email", "").strip()

    if not username or not password:
        raise HTTPException(400, "Username and password required")

    doc = register_user(username, password, email)
    token = _create_session(username)

    return {"success": True, "username": username, "token": token}


@app.post("/users/login")
def api_user_login(payload: dict = Body(...)):
    username = payload.get("username", "").strip()
    password = payload.get("password", "").strip()
    return login_user(username, password)


@app.get("/users/me")
def api_users_me(current=Depends(get_current_user)):
    return {"username": current}


import os, json, base64, hashlib, secrets
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, List

import requests
from fastapi import FastAPI, HTTPException, Body, Depends, Header
from fastapi.middleware.cors import CORSMiddleware

# ======================================================
# CONFIG
# ======================================================

BASE_DIR = os.path.abspath(os.environ.get("DATA_DIR", "./data"))
USERS_LOCAL_ROOT = os.path.join(BASE_DIR, "users")
os.makedirs(USERS_LOCAL_ROOT, exist_ok=True)

GITHUB_REPO = os.environ.get("GITHUB_REPO", "wealthoceaninstitute-commits/Clients")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main")

PASSWORD_SALT = os.environ.get("USER_PASSWORD_SALT", "woi_default_salt")
SESSION_TTL_MINUTES = int(os.environ.get("USER_SESSION_TTL_MIN", "720"))  # 12 hours

_user_sessions: Dict[str, Dict[str, Any]] = {}  # token → {username, expires_at}


# ======================================================
#  GITHUB API HELPERS
# ======================================================

def _github_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

def _github_api(url: str):
    return f"https://api.github.com/repos/{GITHUB_REPO}/{url}"

def _github_write(path: str, content: str, message: str):
    """Write or update a file in GitHub repo."""
    url = _github_api(f"contents/{path}")

    # Check if file exists
    r = requests.get(url, headers=_github_headers())
    sha = r.json().get("sha") if r.status_code == 200 else None

    data = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        data["sha"] = sha

    resp = requests.put(url, headers=_github_headers(), json=data)
    if resp.status_code >= 300:
        raise HTTPException(500, f"GitHub write failed: {resp.text}")

def _github_delete(path: str, message="delete file"):
    """Delete a file in GitHub repo."""
    url = _github_api(f"contents/{path}")

    r = requests.get(url, headers=_github_headers())
    if r.status_code != 200:
        return False

    sha = r.json()["sha"]

    resp = requests.delete(url, headers=_github_headers(), json={
        "message": message,
        "sha": sha,
        "branch": GITHUB_BRANCH,
    })

    return resp.status_code < 300


def _github_mkdir(path: str):
    """
    GitHub does not support real folders,
    so we create `.keep` file to ensure folder exists.
    """
    keep_path = f"{path}/.keep"
    _github_write(keep_path, "", f"Create folder {path}")


# ======================================================
#  MULTI-USER: PASSWORD + SESSION
# ======================================================

def _hash_password(raw: str) -> str:
    raw = (raw or "").strip()
    return hashlib.sha256((raw + PASSWORD_SALT).encode()).hexdigest()

def _create_session(username: str) -> str:
    token = secrets.token_urlsafe(32)
    expiry = datetime.utcnow() + timedelta(minutes=SESSION_TTL_MINUTES)
    _user_sessions[token] = {"username": username, "expires_at": expiry}
    return token

def _get_user_by_token(token: str) -> str:
    sess = _user_sessions.get(token)
    if not sess:
        raise HTTPException(401, "Invalid session")

    if datetime.utcnow() > sess["expires_at"]:
        _user_sessions.pop(token, None)
        raise HTTPException(401, "Session expired")

    return sess["username"]

def get_current_user(x_auth_token: Optional[str] = Header(None)):
    if not x_auth_token:
        return None
    return _get_user_by_token(x_auth_token)


# ======================================================
#  USER FOLDER HELPERS
# ======================================================

def _safe(name: str) -> str:
    return "".join(c for c in name if c.isalnum() or c in ("-", "_")) or "x"

def _user_root(username: str) -> str:
    return os.path.join(USERS_LOCAL_ROOT, _safe(username))

def _user_json_path(username: str) -> str:
    return os.path.join(_user_root(username), "user.json")

def _user_clients_folder(username: str, broker: str) -> str:
    return os.path.join(_user_root(username), "clients", broker)

def _ensure_local_user_tree(username: str):
    root = _user_root(username)
    os.makedirs(root, exist_ok=True)
    os.makedirs(os.path.join(root, "clients", "dhan"), exist_ok=True)
    os.makedirs(os.path.join(root, "clients", "motilal"), exist_ok=True)

def _ensure_github_user_tree(username: str):
    base = f"users/{_safe(username)}"
    _github_mkdir(base)
    _github_mkdir(f"{base}/clients")
    _github_mkdir(f"{base}/clients/dhan")
    _github_mkdir(f"{base}/clients/motilal")


# ======================================================
#  USER REGISTRATION
# ======================================================

def register_user_service(username: str, password: str, email: str):
    username = _safe(username)

    # Local folder
    _ensure_local_user_tree(username)

    # GitHub folder
    _ensure_github_user_tree(username)

    user_doc = {
        "username": username,
        "email": email,
        "password_hash": _hash_password(password),
        "created_at": datetime.utcnow().isoformat() + "Z"
    }

    # Save locally
    with open(_user_json_path(username), "w") as f:
        json.dump(user_doc, f, indent=2)

    # Save to GitHub
    _github_write(
        f"users/{username}/user.json",
        json.dumps(user_doc, indent=2),
        f"Create user {username}"
    )


# ======================================================
#  FASTAPI SETUP
# ======================================================

app = FastAPI(title="Multi-User Multi-Broker Router")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],     # you can restrict later
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======================================================
#  USER ROUTES
# ======================================================

@app.post("/users/register")
def register_user(payload: Dict[str, Any] = Body(...)):
    username = payload.get("username", "").strip()
    password = payload.get("password", "").strip()
    email = payload.get("email", "").strip()

    if not username or not password:
        raise HTTPException(400, "username and password required")

    # Check if exists
    if os.path.exists(_user_json_path(username)):
        raise HTTPException(400, "User already exists")

    register_user_service(username, password, email)

    token = _create_session(username)
    return {"success": True, "username": username, "token": token}


@app.post("/users/login")
def login_user(payload: Dict[str, Any] = Body(...)):
    username = payload.get("username", "").strip()
    password = payload.get("password", "").strip()

    p = _user_json_path(username)
    if not os.path.exists(p):
        raise HTTPException(400, "User not found")

    with open(p, "r") as f:
        doc = json.load(f)

    if _hash_password(password) != doc.get("password_hash"):
        raise HTTPException(400, "Invalid password")

    token = _create_session(username)
    return {"success": True, "username": username, "token": token}


@app.get("/users/me")
def users_me(current=Depends(get_current_user)):
    if not current:
        raise HTTPException(401, "Not authenticated")
    return {"username": current}

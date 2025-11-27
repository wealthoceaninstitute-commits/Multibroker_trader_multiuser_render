# backend/MultiBroker_Router.py

import os, json, base64, logging, uuid, hashlib
from datetime import datetime
from typing import Dict, Any, List, Optional

import requests
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

APP_TITLE = "Wealth Ocean Multi-Broker Router"
APP_VERSION = "0.6.1"

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title=APP_TITLE, version=APP_VERSION)

# ---------------------------------------------------------
# CORS configuration – uses ALLOWED_ORIGINS from env
# ---------------------------------------------------------
DEFAULT_FRONTEND = "https://multibrokertradermultiuser-production-f735.up.railway.app"
allowed_env = os.getenv("ALLOWED_ORIGINS", "").strip()

if allowed_env:
    ORIGINS = [
        o.strip().rstrip("/")  # normalize (no trailing /)
        for o in allowed_env.split(",")
        if o.strip()
    ]
else:
    ORIGINS = [DEFAULT_FRONTEND]

logger.info(f"CORS allowed origins: {ORIGINS}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# Local filesystem cache (optional – Railway can wipe it)
# ---------------------------------------------------------
DATA_DIR = os.path.abspath(
    os.getenv("DATA_DIR", os.path.join(os.path.dirname(__file__), "data"))
)
USERS_FILE = os.path.join(DATA_DIR, "users.json")


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def load_json(path: str, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"load_json failed for {path}: {e}")
        return default


def save_json(path: str, data) -> None:
    ensure_dir(os.path.dirname(path))
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------------------------------------------------------
# GitHub sync configuration (source of truth)
# ---------------------------------------------------------
DEFAULT_GITHUB_REPO = "wealthoceaninstitute-commits/Clients"
GITHUB_REPO = os.getenv("GITHUB_REPO", DEFAULT_GITHUB_REPO)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")

ENABLE_GITHUB = bool(GITHUB_TOKEN)

if ENABLE_GITHUB:
    logger.info(
        f"GitHub sync ENABLED: repo={GITHUB_REPO}, branch={GITHUB_BRANCH} (token present)"
    )
else:
    logger.warning(
        "GitHub sync DISABLED (GITHUB_TOKEN not set). "
        "Set GITHUB_TOKEN env var to enable."
    )


def _gh_headers():
    return {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def _gh_url(path: str) -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO}/contents/{path}"


def github_read_json(path: str, default):
    """Read JSON file from GitHub repo."""
    if not ENABLE_GITHUB:
        return default

    url = _gh_url(path)
    try:
        r = requests.get(url, headers=_gh_headers(), timeout=20)
    except Exception as e:
        logger.error(f"GitHub GET error for {path}: {e}")
        return default

    if r.status_code == 404:
        return default
    if r.status_code != 200:
        logger.error(f"GitHub GET failed for {path}: {r.status_code} {r.text}")
        return default

    try:
        content_b64 = r.json().get("content", "")
        raw = base64.b64decode(content_b64).decode("utf-8")
        return json.loads(raw)
    except Exception as e:
        logger.error(f"GitHub JSON decode failed for {path}: {e}")
        return default


def github_write_file(path: str, content: str, message: str) -> None:
    """Create or update a file in GitHub repo."""
    if not ENABLE_GITHUB:
        return

    url = _gh_url(path)
    sha = None

    try:
        r = requests.get(url, headers=_gh_headers(), timeout=20)
    except Exception as e:
        logger.error(f"GitHub GET error for {path}: {e}")
        return

    if r.status_code == 200:
        sha = r.json().get("sha")
    elif r.status_code not in (404,):
        logger.error(f"GitHub GET failed for {path}: {r.status_code} {r.text}")
        return

    payload = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    try:
        resp = requests.put(url, headers=_gh_headers(), json=payload, timeout=25)
    except Exception as e:
        logger.error(f"GitHub PUT error for {path}: {e}")
        return

    if resp.status_code not in (200, 201):
        logger.error(f"GitHub write failed for {path}: {resp.status_code} {resp.text}")
    else:
        logger.info(f"GitHub write OK for {path}")


def github_delete_file(path: str, message: str) -> None:
    """Delete a file from GitHub repo (if it exists)."""
    if not ENABLE_GITHUB:
        return

    url = _gh_url(path)
    try:
        r = requests.get(url, headers=_gh_headers(), timeout=20)
    except Exception as e:
        logger.error(f"GitHub GET-before-delete error for {path}: {e}")
        return

    if r.status_code == 404:
        return
    if r.status_code != 200:
        logger.error(
            f"GitHub GET-before-delete failed for {path}: {r.status_code} {r.text}"
        )
        return

    sha = r.json().get("sha")
    payload = {"message": message, "sha": sha, "branch": GITHUB_BRANCH}

    try:
        resp = requests.delete(url, headers=_gh_headers(), json=payload, timeout=25)
    except Exception as e:
        logger.error(f"GitHub DELETE error for {path}: {e}")
        return

    if resp.status_code not in (200, 204):
        logger.error(f"GitHub delete failed for {path}: {resp.status_code} {resp.text}")
    else:
        logger.info(f"GitHub delete OK for {path}")


# ---------------------------------------------------------
# User & auth logic – stored in GitHub
# ---------------------------------------------------------
ACTIVE_TOKENS: Dict[str, str] = {}  # token -> username


class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=4, max_length=100)


class UserLoginRequest(BaseModel):
    username: str
    password: str


class AuthResponse(BaseModel):
    success: bool = True
    username: str
    token: str


def _hash_password(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _verify_password(raw: str, hashed: str) -> bool:
    return _hash_password(raw) == hashed


def _user_root(username: str) -> str:
    return os.path.join(DATA_DIR, "users", username)


def _clients_root(username: str) -> str:
    return os.path.join(_user_root(username), "clients")


def _groups_file(username: str) -> str:
    return os.path.join(_user_root(username), "groups.json")


def _copy_file(username: str) -> str:
    return os.path.join(_user_root(username), "copy_setups.json")


def _load_users() -> Dict[str, Any]:
    """
    Master user DB loaded from GitHub path: users/users.json
    {
      "pramod": { "password_hash": "...", "created_at": "...", "updated_at": "...", ... },
      ...
    }
    """
    if ENABLE_GITHUB:
        data = github_read_json("users/users.json", {})
    else:
        data = load_json(USERS_FILE, {})
    if not isinstance(data, dict):
        data = {}
    return data


def _save_users(data: Dict[str, Any]) -> None:
    """
    Save master user DB back to GitHub (and optionally local cache).
    """
    if ENABLE_GITHUB:
        github_write_file(
            "users/users.json",
            json.dumps(data, indent=2),
            "Update users DB",
        )
    else:
        save_json(USERS_FILE, data)


def get_current_user(x_auth_token: str = Header(..., alias="x-auth-token")) -> str:
    username = ACTIVE_TOKENS.get(x_auth_token)
    if not username:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return username


# ------------------------ AUTH ROUTES --------------------------------
@app.post("/users/register", response_model=AuthResponse)
def register(req: UserRegisterRequest):
    users = _load_users()
    uname = req.username.strip()
    logger.info(f"REGISTER attempt: {uname}")

    if uname in users:
        raise HTTPException(status_code=400, detail="Username already exists")

    users[uname] = {
        "password_hash": _hash_password(req.password),
        "created_at": now_str(),
        "updated_at": now_str(),
    }
    _save_users(users)

    # local folders (cache)
    ensure_dir(_user_root(uname))
    ensure_dir(_clients_root(uname))

    # session token
    token = uuid.uuid4().hex
    ACTIVE_TOKENS[token] = uname

    # GitHub: per-user metadata file (no password)
    user_doc = {
        "username": uname,
        "created_at": users[uname]["created_at"],
    }
    github_write_file(
        f"users/{uname}/user.json",
        json.dumps(user_doc, indent=2),
        f"Create user {uname}",
    )

    logger.info(f"REGISTER success for {uname}")
    return AuthResponse(success=True, username=uname, token=token)


@app.post("/users/login", response_model=AuthResponse)
def login(req: UserLoginRequest):
    users = _load_users()
    uname = req.username.strip()
    logger.info(f"LOGIN attempt: {uname}")

    if uname not in users:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    stored = users[uname]
    if not _verify_password(req.password, stored.get("password_hash", "")):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    stored["updated_at"] = now_str()
    stored["last_login_at"] = now_str()
    _save_users(users)

    token = uuid.uuid4().hex
    ACTIVE_TOKENS[token] = uname
    logger.info(f"LOGIN success for {uname}")

    return AuthResponse(success=True, username=uname, token=token)


@app.get("/users/me")
def me(current_user: str = Depends(get_current_user)):
    return {"username": current_user}


# ---------------------------------------------------------
# Clients (per user, multi-broker) + GitHub sync
# ---------------------------------------------------------
class ClientPayload(BaseModel):
    broker: str
    client_id: str
    display_name: Optional[str] = None
    capital: Optional[float] = None
    creds: Dict[str, Any]


def _client_path(username: str, broker: str, client_id: str) -> str:
    safe_broker = broker.replace("/", "_")
    safe_client = client_id.replace("/", "_")
    return os.path.join(_clients_root(username), safe_broker, f"{safe_client}.json")


def _add_or_update_client(username: str, payload: ClientPayload) -> Dict[str, Any]:
    path = _client_path(username, payload.broker, payload.client_id)
    ensure_dir(os.path.dirname(path))

    record = {
        "broker": payload.broker,
        "client_id": payload.client_id,
        "display_name": payload.display_name or payload.client_id,
        "capital": payload.capital,
        "creds": payload.creds,
        "updated_at": now_str(),
    }

    if not os.path.exists(path):
        record["created_at"] = now_str()
    else:
        existing = load_json(path, {})
        if "created_at" in existing:
            record["created_at"] = existing["created_at"]

    save_json(path, record)

    # GitHub sync
    github_write_file(
        f"users/{username}/clients/{payload.broker}/{payload.client_id}.json",
        json.dumps(record, indent=2),
        f"Save client {payload.client_id} for {username}",
    )
    return record


def _list_clients(username: str) -> Dict[str, List[Dict[str, Any]]]:
    root = _clients_root(username)
    result: Dict[str, List[Dict[str, Any]]] = {}

    if not os.path.isdir(root):
        return result

    for broker in os.listdir(root):
        broker_dir = os.path.join(root, broker)
        if not os.path.isdir(broker_dir):
            continue

        items: List[Dict[str, Any]] = []
        for fname in os.listdir(broker_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(broker_dir, fname)
            data = load_json(fpath, {})
            if not data:
                continue

            items.append(
                {
                    "broker": broker,
                    "client_id": data.get("client_id"),
                    "display_name": data.get("display_name") or data.get("client_id"),
                    "capital": data.get("capital"),
                    "created_at": data.get("created_at"),
                    "updated_at": data.get("updated_at"),
                }
            )
        result[broker] = items
    return result


def _delete_client(username: str, broker: str, client_id: str) -> None:
    path = _client_path(username, broker, client_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Client not found")

    os.remove(path)

    github_delete_file(
        f"users/{username}/clients/{broker}/{client_id}.json",
        f"Delete client {client_id} for {username}",
    )


@app.post("/clients/add")
def clients_add(
    payload: ClientPayload, current_user: str = Depends(get_current_user)
):
    record = _add_or_update_client(current_user, payload)
    return {"status": "ok", "client": record}


@app.get("/clients/list")
def clients_list(current_user: str = Depends(get_current_user)):
    return {"status": "ok", "clients": _list_clients(current_user)}


@app.get("/clients/get/{broker}/{client_id}")
def clients_get(
    broker: str, client_id: str, current_user: str = Depends(get_current_user)
):
    path = _client_path(current_user, broker, client_id)
    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="Client not found")
    data = load_json(path, {})
    return {"status": "ok", "client": data}


@app.delete("/clients/delete/{broker}/{client_id}")
def clients_delete(
    broker: str, client_id: str, current_user: str = Depends(get_current_user)
):
    _delete_client(current_user, broker, client_id)
    return {"status": "ok"}


# --------- Alias routes expected by current frontend (/users/*) ---------------
class DeleteClientBody(BaseModel):
    broker: str
    client_id: str


@app.get("/users/clients")
@app.get("/users/get_clients")
def users_clients(current_user: str = Depends(get_current_user)):
    return {"status": "ok", "clients": _list_clients(current_user)}


@app.post("/users/add_client")
def users_add_client(
    payload: ClientPayload, current_user: str = Depends(get_current_user)
):
    record = _add_or_update_client(current_user, payload)
    return {"status": "ok", "client": record}


@app.post("/users/edit_client")
def users_edit_client(
    payload: ClientPayload, current_user: str = Depends(get_current_user)
):
    record = _add_or_update_client(current_user, payload)
    return {"status": "ok", "client": record}


@app.post("/users/delete_client")
def users_delete_client(
    body: DeleteClientBody, current_user: str = Depends(get_current_user)
):
    _delete_client(current_user, body.broker, body.client_id)
    return {"status": "ok"}


# ---------------------------------------------------------
# Groups (per user)  (stored in GitHub)
# ---------------------------------------------------------
class GroupModel(BaseModel):
    name: str
    description: Optional[str] = None
    clients: List[str] = []  # keys like "dhan-AB123"


def _load_groups(username: str) -> List[Dict[str, Any]]:
    if ENABLE_GITHUB:
        data = github_read_json(f"users/{username}/groups.json", [])
    else:
        data = load_json(_groups_file(username), [])
    if not isinstance(data, list):
        data = []
    return data


def _save_groups(username: str, groups: List[Dict[str, Any]]) -> None:
    # cache
    save_json(_groups_file(username), groups)
    # GitHub
    github_write_file(
        f"users/{username}/groups.json",
        json.dumps(groups, indent=2),
        f"Save groups for {username}",
    )


@app.get("/users/groups")
def get_groups(current_user: str = Depends(get_current_user)):
    return {"status": "ok", "groups": _load_groups(current_user)}


@app.post("/users/groups/save")
def save_group(group: GroupModel, current_user: str = Depends(get_current_user)):
    groups = _load_groups(current_user)
    for g in groups:
        if g.get("name") == group.name:
            g.update(group.dict())
            break
    else:
        groups.append(group.dict())
    _save_groups(current_user, groups)
    return {"status": "ok", "groups": groups}


class GroupDeleteBody(BaseModel):
    name: str


@app.post("/users/groups/delete")
def delete_group(
    body: GroupDeleteBody, current_user: str = Depends(get_current_user)
):
    groups = _load_groups(current_user)
    new_groups = [g for g in groups if g.get("name") != body.name]
    _save_groups(current_user, new_groups)
    return {"status": "ok", "groups": new_groups}


# ---------------------------------------------------------
# Copy-trading setups (per user)  (stored in GitHub)
# ---------------------------------------------------------
class CopySetupModel(BaseModel):
    id: Optional[str] = None
    name: str
    source_client: str
    group_name: str
    multiplier: float = 1.0
    active: bool = True


def _load_copy_setups(username: str) -> List[Dict[str, Any]]:
    if ENABLE_GITHUB:
        data = github_read_json(f"users/{username}/copy_setups.json", [])
    else:
        data = load_json(_copy_file(username), [])
    if not isinstance(data, list):
        data = []
    return data


def _save_copy_setups(username: str, setups: List[Dict[str, Any]]) -> None:
    save_json(_copy_file(username), setups)
    github_write_file(
        f"users/{username}/copy_setups.json",
        json.dumps(setups, indent=2),
        f"Save copy setups for {username}",
    )


@app.get("/users/copy/setups")
def get_copy_setups(current_user: str = Depends(get_current_user)):
    return {"status": "ok", "setups": _load_copy_setups(current_user)}


@app.post("/users/copy/save")
def save_copy_setup(
    setup: CopySetupModel, current_user: str = Depends(get_current_user)
):
    setups = _load_copy_setups(current_user)
    if setup.id is None:
        setup.id = uuid.uuid4().hex
        setups.append(setup.dict())
    else:
        for s in setups:
            if s.get("id") == setup.id:
                s.update(setup.dict())
                break
        else:
            setups.append(setup.dict())
    _save_copy_setups(current_user, setups)
    return {"status": "ok", "setups": setups}


class CopyIdBody(BaseModel):
    id: str


@app.post("/users/copy/enable")
def enable_copy(body: CopyIdBody, current_user: str = Depends(get_current_user)):
    setups = _load_copy_setups(current_user)
    for s in setups:
        if s.get("id") == body.id:
            s["active"] = True
            break
    _save_copy_setups(current_user, setups)
    return {"status": "ok", "setups": setups}


@app.post("/users/copy/disable")
def disable_copy(body: CopyIdBody, current_user: str = Depends(get_current_user)):
    setups = _load_copy_setups(current_user)
    for s in setups:
        if s.get("id") == body.id:
            s["active"] = False
            break
    _save_copy_setups(current_user, setups)
    return {"status": "ok", "setups": setups}


@app.post("/users/copy/delete")
def delete_copy(body: CopyIdBody, current_user: str = Depends(get_current_user)):
    setups = _load_copy_setups(current_user)
    setups = [s for s in setups if s.get("id") != body.id]
    _save_copy_setups(current_user, setups)
    return {"status": "ok", "setups": setups}


# ---------------------------------------------------------
# Local dev entry point
# ---------------------------------------------------------
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("MultiBroker_Router:app", host="0.0.0.0", port=8000, reload=True)

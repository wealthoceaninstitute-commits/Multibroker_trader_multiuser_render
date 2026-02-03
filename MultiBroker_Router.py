# MultiBroker_Router.py
import os, json, importlib, base64
from typing import Any, Dict, List,Optional
from fastapi import FastAPI, Body, BackgroundTasks, HTTPException, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from collections import OrderedDict
import importlib, os, time
import threading
import os, sqlite3, threading, requests
from fastapi import Query
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from auth.auth_router import router as auth_router

# 1️⃣ Create the FastAPI app once
app = FastAPI(title="Multi-broker Router")

# 2️⃣ Add CORS middleware.  Allow the deployed frontend origins plus a wildcard
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://multibroker-trader-multiuser.vercel.app",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3️⃣ Include the authentication router.  This registers /auth/register and other routes
app.include_router(auth_router)


# 4️⃣ OPTIONAL health check
@app.get("/")
def health():
    return {"status": "ok"}


from fastapi import Request

@app.middleware("http")
async def debug_requests(request: Request, call_next):
    print("---- DEBUG REQUEST ----")
    print("Path:", request.url.path)
    print("Method:", request.method)
    print("Headers:", dict(request.headers))

    try:
        body = await request.body()
        print("Raw body:", body)
    except Exception as e:
        print("Body read error:", e)

    response = await call_next(request)
    print("Response status:", response.status_code)
    print("-----------------------")
    return response




STAT_KEYS = ["pending", "traded", "rejected", "cancelled", "others"]
summary_data_global: Dict[str, Dict[str, Any]] = {}
SYMBOL_DB_PATH = os.path.join(os.path.abspath(os.environ.get("DATA_DIR", "./data")), "symbols.db")
SYMBOL_TABLE   = "symbols"
SYMBOL_CSV_URL = "https://raw.githubusercontent.com/Pramod541988/Stock_List/refs/heads/main/security_id.csv"
_symbol_db_lock = threading.Lock()



# GitHub helper functions removed: GH_HEADERS, GH_CONTENTS_URL, _github_sync_dir, _github_sync_down_all
# -------- Option B storage --------
BASE_DIR = os.path.abspath(os.environ.get("DATA_DIR", "./data"))

"""
In the original design clients for each broker were stored under
./data/clients/<broker>/<client_id>.json.

This router has been upgraded for multi‑user support.  Client
credentials are now stored under a per‑user directory:
    data/users/<userid>/clients/<broker>/<userid>_<client_id>.json

`_user_clients_root(user)` returns the base directory for a given
user, and `_user_client_path(user, broker, client_id)` returns the
full path for that client.

Old variables DHAN_DIR/MO_DIR are kept for backwards compatibility
with any residual logic but are no longer used by the add/edit client
routes.  They still point to the legacy locations to avoid breaking
other parts of the code that might still reference them.
"""

CLIENTS_ROOT = os.path.join(BASE_DIR, "clients")

# Legacy directories (unused in new user‑aware endpoints)
DHAN_DIR     = os.path.join(CLIENTS_ROOT, "dhan")
MO_DIR       = os.path.join(CLIENTS_ROOT, "motilal")
os.makedirs(DHAN_DIR, exist_ok=True)
os.makedirs(MO_DIR,   exist_ok=True)

# New per‑user storage helper functions
USERS_ROOT = os.path.join(BASE_DIR, "users")
os.makedirs(USERS_ROOT, exist_ok=True)

def _user_clients_root(user_id: str) -> str:
    """
    Absolute path to a user's clients directory.

    data/users/<user>/clients
    """
    safe_user = _safe(user_id)
    return os.path.join(USERS_ROOT, safe_user, "clients")


def _user_client_path(user_id: str, broker: str, client_id: str) -> str:
    """
    Absolute path to a specific client JSON file.

    Final structure:
    data/users/<user>/clients/<broker>/<client_id>.json
    """
    safe_user   = _safe(user_id)
    safe_broker = _safe(broker).lower()
    safe_client = _safe(client_id)

    folder = os.path.join(USERS_ROOT, safe_user, "clients", safe_broker)
    os.makedirs(folder, exist_ok=True)

    return os.path.join(folder, f"{safe_client}.json")




# --- Groups storage (simple) ---
GROUPS_ROOT = os.path.join(BASE_DIR, "groups")
os.makedirs(GROUPS_ROOT, exist_ok=True)

def _group_path(group_id_or_name: str) -> str:
    """Return path for a group json, using safe id/name."""
    return os.path.join(GROUPS_ROOT, f"{_safe(group_id_or_name)}.json")

# --- Copy Trading storage (file-based) ---
COPY_ROOT = os.path.join(BASE_DIR, "copy_setups")
os.makedirs(COPY_ROOT, exist_ok=True)

def _copy_path(setup_id: str) -> str:
    return os.path.join(COPY_ROOT, f"{_safe(setup_id)}.json")

def _read_json(path: str) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}




# ---------- helpers ----------
def _ensure_dirs():
    os.makedirs(os.path.dirname(SYMBOL_DB_PATH), exist_ok=True)
# GitHub helper functions removed: GH_HEADERS, GH_CONTENTS_URL, _github_sync_dir, _github_sync_down_all
# === GitHub persistence helpers ===
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO_OWNER = os.environ.get("GITHUB_REPO_OWNER", "").strip()
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME", "").strip()
GITHUB_BRANCH = os.environ.get("GITHUB_BRANCH", "main").strip() or "main"
GITHUB_SYNC_DISABLED = os.environ.get("GITHUB_SYNC_DISABLED", "").strip().lower() in ("1","true","yes","on")

def _github_enabled() -> bool:
    """
    Determine if GitHub persistence should be enabled.

    This implementation now ignores the ``GITHUB_SYNC_DISABLED`` environment
    variable so long as the required GitHub credentials (token, owner and
    repository name) are present.  In other words, if you configure
    ``GITHUB_TOKEN``, ``GITHUB_REPO_OWNER`` and ``GITHUB_REPO_NAME``, the
    router will always attempt to mirror saved JSON documents to your
    GitHub repository.  This change allows client JSON files to be
    persisted to GitHub without depending on the optional disabling flag.
    """
    return bool(GITHUB_TOKEN and GITHUB_REPO_OWNER and GITHUB_REPO_NAME)

def _gh_headers() -> Dict[str, str]:
    return {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "multibroker-router",
    }

def _gh_contents_url(path_in_repo: str) -> str:
    return f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{path_in_repo}"

def _github_file_write(rel_path: str, content: str) -> None:
    """Write/overwrite a file in the GitHub repo under the `data/` prefix."""
    if not _github_enabled():
        print(f"[GITHUB_DISABLED] skip write: {rel_path}")
        return

    path_in_repo = ("data/" + rel_path.lstrip("/")).replace("\\", "/")
    url = _gh_contents_url(path_in_repo)

    sha = None
    try:
        r0 = requests.get(url, headers=_gh_headers(), params={"ref": GITHUB_BRANCH}, timeout=20)
        if r0.status_code == 200:
            sha = (r0.json() or {}).get("sha")
    except Exception as e:
        print(f"[GITHUB] sha lookup failed (will try create): {e}")

    payload = {
        "message": f"update {path_in_repo}",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    r = requests.put(url, headers=_gh_headers(), json=payload, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub write failed {r.status_code}: {r.text[:300]}")
    print(f"[GITHUB_OK] wrote: {path_in_repo}")

def _github_file_delete(rel_path: str) -> None:
    """Delete a file in the GitHub repo under the `data/` prefix."""
    if not _github_enabled():
        print(f"[GITHUB_DISABLED] skip delete: {rel_path}")
        return

    path_in_repo = ("data/" + rel_path.lstrip("/")).replace("\\", "/")
    url = _gh_contents_url(path_in_repo)

    r0 = requests.get(url, headers=_gh_headers(), params={"ref": GITHUB_BRANCH}, timeout=20)
    if r0.status_code != 200:
        print(f"[GITHUB] delete skip (not found): {path_in_repo}")
        return
    sha = (r0.json() or {}).get("sha")
    if not sha:
        print(f"[GITHUB] delete skip (no sha): {path_in_repo}")
        return

    payload = {"message": f"delete {path_in_repo}", "sha": sha, "branch": GITHUB_BRANCH}
    r = requests.delete(url, headers=_gh_headers(), json=payload, timeout=30)
    if r.status_code not in (200, 204):
        raise RuntimeError(f"GitHub delete failed {r.status_code}: {r.text[:300]}")
    print(f"[GITHUB_OK] deleted: {path_in_repo}")


def refresh_symbol_db_from_github() -> str:
    """
    Download CSV and rebuild SQLite table 'symbols'.
    Creates helpful indexes for fast LIKE queries.
    """
    _ensure_dirs()
    # Download -> dataframe
    r = requests.get(SYMBOL_CSV_URL, timeout=30)
    r.raise_for_status()
    csv_path = os.path.join(os.path.dirname(SYMBOL_DB_PATH), "security_id.csv")
    with open(csv_path, "wb") as f:
        f.write(r.content)
    df = pd.read_csv(csv_path)

    with _symbol_db_lock:
        conn = sqlite3.connect(SYMBOL_DB_PATH)
        try:
            df.to_sql(SYMBOL_TABLE, conn, index=False, if_exists="replace")
            # indexes (ignore failures if columns already indexed / absent)
            try:
                conn.execute(f'CREATE INDEX IF NOT EXISTS idx_sym_symbol ON {SYMBOL_TABLE} ("Stock Symbol");')
            except Exception:
                pass
            try:
                conn.execute(f'CREATE INDEX IF NOT EXISTS idx_sym_exchange ON {SYMBOL_TABLE} (Exchange);')
            except Exception:
                pass
            try:
                conn.execute(f'CREATE INDEX IF NOT EXISTS idx_sym_secid ON {SYMBOL_TABLE} ("Security ID");')
            except Exception:
                pass
            conn.commit()
        finally:
            conn.close()
    return "success"

def _symbol_db_exists() -> bool:
    return os.path.exists(SYMBOL_DB_PATH)

def _lazy_init_symbol_db():
    """Build the DB once if it does not exist."""
    if not _symbol_db_exists():
        try:
            refresh_symbol_db_from_github()
        except Exception as e:
            print("❌ Symbol DB init failed:", e)


@app.post("/refresh_symbols")
def router_refresh_symbols():
    """Force refresh the symbol master from GitHub into SQLite."""
    try:
        msg = refresh_symbol_db_from_github()
        return {"status": msg}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/search_symbols")
def router_search_symbols(q: str = Query(""), exchange: str = Query("")):
    """
    Typeahead search with ranking:
      0 = exact match on whole query
      1 = symbol startswith whole query
      2 = symbol contains whole query (anywhere)
    """
    _lazy_init_symbol_db()
    raw = (q or "").strip().lower()
    exch = (exchange or "").strip().upper()
    if not raw:
        return {"results": []}

    # split into words for WHERE (AND-of-words)
    words = [w for w in raw.split() if w]
    if not words:
        return {"results": []}

    where_sql, where_params = [], []
    for w in words:
        where_sql.append('LOWER([Stock Symbol]) LIKE ?')
        where_params.append(f"%{w}%")
    if exch:
        where_sql.append('UPPER(Exchange) = ?')
        where_params.append(exch)

    # ranking based on full raw query (not just first word)
    rank_params = [raw, f"{raw}%", f"%{raw}%"]

    sql = f"""
        SELECT
            Exchange,
            [Stock Symbol],
            [Security ID],
            CASE
                WHEN LOWER([Stock Symbol]) = ?     THEN 0
                WHEN LOWER([Stock Symbol]) LIKE ?  THEN 1
                WHEN LOWER([Stock Symbol]) LIKE ?  THEN 2
                ELSE 3
            END AS rank_score
        FROM {SYMBOL_TABLE}
        WHERE {' AND '.join(where_sql)}
        ORDER BY rank_score, [Stock Symbol]
        LIMIT 200
    """

    with _symbol_db_lock:
        conn = sqlite3.connect(SYMBOL_DB_PATH)
        try:
            cur = conn.execute(sql, rank_params + where_params)
            rows = cur.fetchall()
        finally:
            conn.close()

    results = [
        {"id": f"{r[0]}|{r[1]}|{r[2]}", "text": f"{r[0]} | {r[1]}"}
        for r in rows
    ]
    return {"results": results}


@app.on_event("startup")
def _symbols_startup():
    _lazy_init_symbol_db()
    print(f"[startup] symbols ready | github={'on' if _github_enabled() else 'off'} | branch={GITHUB_BRANCH}")


def _safe(s: str) -> str:
    s = (s or "").strip().replace(" ", "_")
    return "".join(ch for ch in s if ch.isalnum() or ch in ("_", "-"))

def _pick(*vals) -> str:
    for v in vals:
        if v is None: continue
        s = str(v).strip()
        if s: return s
    return ""

def _folder_for(broker: str) -> str:
    return DHAN_DIR if broker == "dhan" else MO_DIR

def _path_for(broker: str, userid: str) -> str:
    return os.path.join(_folder_for(broker), f"{_safe(userid)}.json")

def _load(path: str) -> Dict[str, Any]:
    with open(path, "r") as f: return json.load(f)

def _save(path: str, data: Dict[str, Any]):
    """
    Write a JSON document to disk and mirror it to a GitHub repository if configured.
    """
    # ensure local directory exists
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # write to local file
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    # replicate to GitHub
    try:
        rel_path = os.path.relpath(path, BASE_DIR)
        # Normalise path separators for GitHub
        rel_path = rel_path.replace("\\", "/")
        _github_file_write(rel_path, json.dumps(data, indent=4))
    except Exception as e:
        print(f"[GITHUB_ERR] {e}")

# ---------- minimal save (no hard failures) ----------
def _save_minimal(broker: str, payload: Dict[str, Any]) -> str:
    """
    Stores only user-provided credential fields (no auto token logic).
    Normalized for Dhan & Motilal.
    """
    userid = _pick(payload.get("userid"), payload.get("client_id"))
    if not userid:
        raise HTTPException(status_code=400, detail="client_id / userid is required")

    name = _pick(payload.get("name"), payload.get("display_name"), userid)

    if broker == "dhan":
        doc = {
            "userid": userid,
            "name": name,
            "mobile": _pick(payload.get("mobile"), payload.get("mobile_number")),
            "pin": _pick(payload.get("pin")),
            "apikey": _pick(payload.get("apikey")),
            "api_secret": _pick(payload.get("api_secret")),
            "totpkey": _pick(payload.get("totpkey")),
            "capital": payload.get("capital", ""),
            "session_active": False
        }

    else:  # motilal — unchanged
        creds = payload.get("creds") or {}
        doc = {
            "userid": userid,
            "name": name,
            "password": _pick(payload.get("password"), creds.get("password")),
            "pan": _pick(payload.get("pan"), creds.get("pan")),
            "apikey": _pick(payload.get("apikey"), creds.get("apikey")),
            "totpkey": _pick(payload.get("totpkey"), creds.get("totpkey")),
            "capital": payload.get("capital", ""),
            "session_active": False,
        }

    path = _path_for(broker, userid)
    _save(path, doc)
    return path


def _update_minimal(broker: str, payload: Dict[str, Any]) -> str:
    """
    Update ONLY modal fields + session_active.
    - Preserves existing non-empty values when new values are empty/missing.
    - Supports userid/broker change (renames/moves file).
    Optional fields for rename:
      original_userid, original_broker
    """
    # Where the record *was* (if provided)
    old_userid  = _pick(payload.get("original_userid"), payload.get("old_userid"))
    old_broker  = (_pick(payload.get("original_broker"), payload.get("old_broker")) or broker).lower()
    old_path    = _path_for(old_broker, old_userid) if old_userid else None

    # Where the record *should be* after edit
    userid      = _pick(payload.get("userid"), payload.get("client_id"), old_userid)
    if not userid:
        raise HTTPException(status_code=400, detail="client_id / userid is required for edit")
    name        = _pick(payload.get("name"), payload.get("display_name"), userid)
    new_path    = _path_for(broker, userid)

    # Load what we already have (prefer old if exists, otherwise new)
    existing: Dict[str, Any] = {}
    try:
        if old_path and os.path.exists(old_path):
            existing = _load(old_path)
        elif os.path.exists(new_path):
            existing = _load(new_path)
    except Exception:
        existing = {}

    # Build merged doc (keep existing field when new candidate is empty)
  # Build merged doc (keep existing field when new candidate is empty)
    # Build merged doc (keep existing field when new candidate is empty)
    if broker == "dhan":
        doc = {
            "userid": userid,
            "name": _pick(name, existing.get("name")),
            "mobile": _pick(
                payload.get("mobile"),
                payload.get("mobile_number"),
                existing.get("mobile"),
            ),
            "pin": _pick(payload.get("pin"), existing.get("pin")),
            "apikey": _pick(payload.get("apikey"), existing.get("apikey")),
            "api_secret": _pick(payload.get("api_secret"), existing.get("api_secret")),
            "totpkey": _pick(payload.get("totpkey"), existing.get("totpkey")),
            "capital": payload.get("capital", existing.get("capital")),
            "session_active": existing.get("session_active", False),
        }
    else:  # motilal
        creds = payload.get("creds") or {}
        doc = {
            "name": _pick(name, existing.get("name")),
            "userid": userid,
            "password": _pick(
                payload.get("password"),
                creds.get("password"),
                existing.get("password"),
            ),
            "pan": _pick(payload.get("pan"), creds.get("pan"), existing.get("pan")),
            "mpin": _pick(payload.get("mpin"), creds.get("mpin"), existing.get("mpin")),
            "apikey": _pick(
                payload.get("apikey"),
                creds.get("apikey"),
                existing.get("apikey"),
            ),
            "totpkey": _pick(
                payload.get("totpkey"),
                creds.get("totpkey"),
                existing.get("totpkey"),
            ),
            "capital": payload.get("capital", existing.get("capital")),
            "session_active": existing.get("session_active", False),
        }


    # Write new file
    _save(new_path, doc)

    # If we changed userid/broker, remove the old file
    if old_path and os.path.abspath(old_path) != os.path.abspath(new_path):
        try:
            if os.path.exists(old_path):
                os.remove(old_path)
        except Exception:
            pass

    return new_path


def _has_required_for_login(broker: str, c: Dict[str, Any]) -> bool:
    if broker == "dhan":
        return bool((c.get("apikey") or "").strip())
    return all((
        (c.get("password") or "").strip(),
        (c.get("pan") or "").strip(),
        (c.get("apikey") or "").strip(),
        (c.get("totpkey") or "").strip()
    ))

def _dispatch_login(broker: str, path: str):
    try:
        client = _load(path)

        # 🔥 DEBUG PRINT — SHOW EXACT CLIENT LOADED FROM GITHUB/DISK
        try:
            print("\n================= CLIENT DEBUG =================")
            print(f"[debug] broker      = {broker}")
            print(f"[debug] file path   = {path}")
            print(f"[debug] client_json =\n{json.dumps(client, indent=2)}")
            print("===============================================\n")
        except Exception as e:
            print(f"[debug] unable to print client JSON: {e}")

        # Validate minimum fields
        if not _has_required_for_login(broker, client):
            print(f"[router] skip login ({broker}/{client.get('userid')}): missing required fields")
            return

        # Module selection
        mod_name = "Broker_dhan" if broker == "dhan" else "Broker_motilal"
        mod = importlib.import_module(mod_name)
        login_fn = getattr(mod, "login", None)
        if not callable(login_fn):
            print(f"[router] {mod_name}.login() not found")
            return

        # Perform login
        result = login_fn(client)

        # Determine login status
        ok = bool(result if not isinstance(result, dict) else result.get("ok", True))

        # Store token metadata for Dhan login dict
        if isinstance(result, dict):
            if result.get("token_validity_raw") or result.get("token_validity_iso"):
                client["token_validity"] = (
                    result.get("token_validity_raw") or result.get("token_validity_iso")
                )
                client["token_validity_iso"] = result.get("token_validity_iso", "")

            if result.get("token_days_left") is not None:
                client["token_days_left"] = int(result["token_days_left"])

            if result.get("token_warning") is not None:
                client["token_warning"] = bool(result["token_warning"])

            from datetime import datetime
            client["last_token_check"] = datetime.utcnow().isoformat() + "Z"

            if result.get("message"):
                print(f"[router] login message: {result['message']}")

        # Save session status
        client["session_active"] = ok
        _save(path, client)

    except ModuleNotFoundError:
        print(f"[router] module for {broker} not found (Broker_dhan.py / Broker_motilal.py)")
    except Exception as e:
        print(f"[router] login error ({broker}): {e}")



def _delete_client_file(broker: str, userid: str) -> bool:
    """Remove a single client's JSON file. Returns True if deleted, False if it didn't exist."""
    broker = (broker or "").lower()
    if not broker or not userid:
        raise HTTPException(status_code=400, detail="broker and userid are required")
    path = _path_for(broker, userid)
    try:
        os.remove(path)
        # Remove from GitHub as well
        try:
            rel_path = os.path.relpath(path, BASE_DIR).replace("\\", "/")
            _github_file_delete(rel_path)
        except Exception:
            pass
        return True
    except FileNotFoundError:
        return False
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Failed deleting {broker}/{userid}: {e}")
    

def _list_groups() -> list[dict]:
    items = []
    try:
        for fn in os.listdir(GROUPS_ROOT):
            if not fn.endswith(".json"):
                continue
            doc = _read_json(os.path.join(GROUPS_ROOT, fn))
            if doc and isinstance(doc, dict):
                # minimal sanitize
                doc["id"] = doc.get("id") or os.path.splitext(fn)[0]
                doc["name"] = doc.get("name") or doc["id"]
                doc["multiplier"] = float(doc.get("multiplier", 1))
                doc["members"] = doc.get("members") or []
                items.append(doc)
    except FileNotFoundError:
        pass
    # sort by name for stable UI
    items.sort(key=lambda d: (d.get("name") or "").lower())
    return items

def _find_group_path(id_or_name: str) -> str | None:
    """Find a group's json path by id or name (case-insensitive)."""
    key = _safe(id_or_name)
    # direct filename hit
    p = os.path.join(GROUPS_ROOT, f"{key}.json")
    if os.path.exists(p):
        return p
    # scan by name inside files
    needle = (id_or_name or "").strip().lower()
    try:
        for fn in os.listdir(GROUPS_ROOT):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(GROUPS_ROOT, fn)
            doc = _read_json(path)
            nm = (doc.get("name") or "").strip().lower()
            if nm and nm == needle:
                return path
    except FileNotFoundError:
        return None
    return None

def _find_copy_path(id_or_name: str) -> str | None:
    """Find a copy-trading setup by id (filename) or by name (case-insensitive)."""
    key = _safe(id_or_name or "")
    p = _copy_path(key)
    if os.path.exists(p):
        return p
    needle = (id_or_name or "").strip().lower()
    try:
        for fn in os.listdir(COPY_ROOT):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(COPY_ROOT, fn)
            doc = _read_json(path) or {}
            nm = (doc.get("name") or "").strip().lower()
            if nm == needle:
                return path
    except FileNotFoundError:
        pass
    return None


def _set_copy_enabled(payload: Dict[str, Any], value: bool):
    """
    Toggle enabled flag for setups.
    Accepts: { ids:[...], names:[...], id?, name? }
    """
    ids = list(payload.get("ids") or [])
    names = list(payload.get("names") or [])
    if payload.get("id"):
        ids.append(str(payload["id"]))
    if payload.get("name"):
        names.append(str(payload["name"]))

    targets = [str(x) for x in (ids + names)]
    if not targets:
        raise HTTPException(status_code=400, detail="provide 'ids' or 'names'")

    changed: List[str] = []
    for t in targets:
        p = _find_copy_path(t)
        if not p:
            continue
        doc = _read_json(p) or {}
        doc["enabled"] = bool(value)
        # ensure id field is present/stable
        doc["id"] = doc.get("id") or os.path.splitext(os.path.basename(p))[0]
        _save(p, doc)
        changed.append(doc["id"])

    return {"success": True, "changed": changed, "enabled": value}

def _unique_copy_id(name: str) -> str:
    base = _safe(name) or "setup"
    cid = base
    i = 1
    while os.path.exists(_copy_path(cid)):
        i += 1
        cid = f"{base}-{i}"
    return cid

def _extract_children(raw_children) -> list[str]:
    """Normalize children to a de-duplicated list of userids (strings)."""
    out: list[str] = []
    if isinstance(raw_children, list):
        for ch in raw_children:
            if isinstance(ch, str):
                cid = ch.strip()
            elif isinstance(ch, dict):
                cid = _pick(ch.get("userid"), ch.get("client_id"), ch.get("id"),
                            ch.get("value"), ch.get("account"))
            else:
                cid = ""
            if cid and cid not in out:
                out.append(str(cid))
    return out

def _build_multipliers(children: list[str], rawm) -> dict[str, float]:
    """Map each child to a float multiplier (default 1.0)."""
    mm: dict[str, float] = {}
    rawm = rawm or {}
    for c in children:
        try:
            mm[c] = float(rawm.get(c, 1))
        except Exception:
            mm[c] = 1.0
    return mm






# ---------- routes ----------



@app.get("/health")
def health():
    status = {}
    for key, mod_name in (("dhan","Broker_dhan"), ("motilal","Broker_motilal")):
        try:
            importlib.import_module(mod_name)
            status[key] = "ready"
        except ModuleNotFoundError:
            status[key] = "missing"
        except Exception as e:
            status[key] = f"error: {e}"
    return {"ok": True, "brokers": status}

@app.post("/clients/add")
def add_client(
    background_tasks: BackgroundTasks,
    payload: Dict[str, Any] = Body(...),
    user_id: str = Header(..., alias="X-User-Id"),
):
    """
    Adds a broker client under the logged-in user.

    Header:
        X-User-Id

    Saves to:
        data/users/<user>/clients/<broker>/<user>_<clientid>.json
    """

    if not user_id:
        raise HTTPException(400, "Missing X-User-Id header")

    broker = (_pick(payload.get("broker")) or "motilal").lower()
    if broker not in ("dhan", "motilal"):
        raise HTTPException(400, f"Unsupported broker: {broker}")

    client_id = _pick(payload.get("client_id"), payload.get("userid"))
    if not client_id:
        raise HTTPException(400, "client_id / userid required")

    name = _pick(payload.get("name"), payload.get("display_name"), client_id)

    # -------------------------
    # Broker-specific payload
    # -------------------------

    if broker == "dhan":
        doc = {
            "broker": "dhan",
            "userid": client_id,
            "name": name,
            "mobile": _pick(payload.get("mobile"), payload.get("mobile_number")),
            "pin": payload.get("pin"),
            "apikey": payload.get("apikey"),
            "api_secret": payload.get("api_secret"),
            "totpkey": payload.get("totpkey"),
            "capital": payload.get("capital", ""),
            "session_active": False,
            "created_at": datetime.utcnow().isoformat(),
        }

    else:  # motilal
        creds = payload.get("creds") or {}
        doc = {
            "broker": "motilal",
            "userid": client_id,
            "name": name,
            "password": _pick(payload.get("password"), creds.get("password")),
            "pan": _pick(payload.get("pan"), creds.get("pan")),
            "apikey": _pick(payload.get("apikey"), creds.get("apikey")),
            "totpkey": _pick(payload.get("totpkey"), creds.get("totpkey")),
            "capital": payload.get("capital", ""),
            "session_active": False,
            "created_at": datetime.utcnow().isoformat(),
        }

    # -------------------------
    # Persist + login
    # -------------------------

    path = _user_client_path(user_id, broker, client_id)
    _save(path, doc)

    background_tasks.add_task(_dispatch_login, broker, path)

    return {
        "success": True,
        "broker": broker,
        "client_id": client_id,
        "message": "Client saved. Login triggered if credentials are valid.",
    }

@app.post("/add_client")
def add_client_legacy(
    background_tasks: BackgroundTasks,
    payload: Dict[str, Any] = Body(...),
    user_id: Optional[str] = Header(None, alias="X-User-Id"),
):
    """
    Legacy alias for older frontend which posts to /add_client.

    Fixes:
    - FastAPI must inject BackgroundTasks (so the login task executes)
    - Ensure we pass arguments to add_client() using the correct parameter names

    This endpoint will accept user id from:
      1) Header: X-User-Id
      2) Payload: user_id / userId / userid / owner_userid
    """
    uid = (user_id or "").strip() or _pick(
        payload.get("user_id"),
        payload.get("userId"),
        payload.get("userid"),
        payload.get("owner_userid"),
    )
    if not uid:
        raise HTTPException(status_code=400, detail="Missing user id. Send X-User-Id header (recommended).")

    return add_client(background_tasks=background_tasks, payload=payload, user_id=uid)
@app.post("/clients/edit")
def edit_client(
    background_tasks: BackgroundTasks,
    payload: Dict[str, Any] = Body(...),
    user_id: str = Header(..., alias="X-User-Id"),
):
    """
    Edit an existing client for the authenticated user.  Accepts the
    same payload shape as `/clients/add`, plus optional
    `original_broker`/`original_userid` (or old_broker/old_userid) when
    renaming or moving a client.  Fields left blank will preserve
    existing values.  After saving, a background login is triggered.
    """
    user_id = (user_id or user_id_q or "").strip().lower()
    if not user_id:
        return []

    broker = (_pick(payload.get("broker")) or "motilal").lower()
    if broker not in ("dhan", "motilal"):
        raise HTTPException(status_code=400, detail=f"Unknown broker '{broker}'")

    # Determine the old identifiers (for rename/move)
    old_client_id = _pick(payload.get("original_userid"), payload.get("old_userid"))
    old_broker    = (_pick(payload.get("original_broker"), payload.get("old_broker")) or broker).lower()

    # Determine new identifiers
    client_id = _pick(payload.get("client_id"), payload.get("userid"), old_client_id)
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id / userid is required for edit")
    name      = _pick(payload.get("name"), payload.get("display_name"), client_id)

    # Resolve old and new paths
    old_path = None
    if old_client_id:
        old_path = _user_client_path(user_id, old_broker, old_client_id)
    new_path = _user_client_path(user_id, broker, client_id)

    # Load existing data (prefer old if exists, otherwise new)
    existing: Dict[str, Any] = {}
    try:
        if old_path and os.path.exists(old_path):
            existing = _load(old_path)
        elif os.path.exists(new_path):
            existing = _load(new_path)
    except Exception:
        existing = {}

    # Merge fields by broker
    if broker == "dhan":
        doc = {
            "userid": client_id,
            "name": _pick(name, existing.get("name")),
            "mobile": _pick(
                payload.get("mobile"),
                payload.get("mobile_number"),
                existing.get("mobile"),
            ),
            "pin": _pick(payload.get("pin"), existing.get("pin")),
            "apikey": _pick(payload.get("apikey"), existing.get("apikey")),
            "api_secret": _pick(payload.get("api_secret"), existing.get("api_secret")),
            "totpkey": _pick(payload.get("totpkey"), existing.get("totpkey")),
            "capital": payload.get("capital", existing.get("capital")),
            "session_active": existing.get("session_active", False),
        }
    else:
        creds = payload.get("creds") or {}
        doc = {
            "userid": client_id,
            "name": _pick(name, existing.get("name")),
            "password": _pick(
                payload.get("password"),
                creds.get("password"),
                existing.get("password"),
            ),
            "pan": _pick(
                payload.get("pan"),
                creds.get("pan"),
                existing.get("pan"),
            ),
            "apikey": _pick(
                payload.get("apikey"),
                creds.get("apikey"),
                existing.get("apikey"),
            ),
            "totpkey": _pick(
                payload.get("totpkey"),
                creds.get("totpkey"),
                existing.get("totpkey"),
            ),
            "capital": payload.get("capital", existing.get("capital")),
            "session_active": existing.get("session_active", False),
        }

    # Write new file
    _save(new_path, doc)
    # If moved/renamed, remove the old file
    if old_path and os.path.abspath(old_path) != os.path.abspath(new_path):
        try:
            if os.path.exists(old_path):
                os.remove(old_path)
        except Exception:
            pass
    # Trigger login
    background_tasks.add_task(_dispatch_login, broker, new_path)
    return {"success": True, "message": f"Updated for {broker}. Login started if fields complete."}
# 
# 
@app.get("/clients")
def clients_rows(user_id: str = Header(..., alias="X-User-Id")):
    """
    List all clients for the authenticated user.  Each row contains
    minimal client details used by the UI.  Clients are loaded from
    `data/users/<user>/clients/<broker>`.
    """
    user_id = (user_id or user_id_q or "").strip().lower()
    if not user_id:
        return {"clients": []}
    rows: List[Dict[str, Any]] = []
    for broker in ("dhan", "motilal"):
        folder = os.path.join(_user_clients_root(user_id), broker)
        try:
            for fn in os.listdir(folder):
                if not fn.endswith(".json"):
                    continue
                path = os.path.join(folder, fn)
                try:
                    d = _load(path)
                    rows.append({
                        "name": d.get("name", ""),
                        "display_name": d.get("name", ""),
                        "client_id": d.get("userid", ""),
                        "capital": d.get("capital", ""),
                        "status": "logged_in" if d.get("session_active") else "logged_out",
                        "session_active": bool(d.get("session_active", False)),
                        "broker": broker,
                    })
                except Exception:
                    pass
        except FileNotFoundError:
            continue
    return rows
# 
@app.get("/get_clients")
def get_clients_legacy(user_id: str = Header(..., alias="X-User-Id")):
    """
    Legacy endpoint to support old UI format.  Returns a list of
    clients with simplified fields.
    """
    rows = clients_rows(user_id)  # reuse new implementation
    return {"clients": [
        {
            "name": r["name"],
            "client_id": r["client_id"],
            "capital": r["capital"],
            "session": "Logged in" if r["session_active"] else "Logged out",
        }
        for r in rows
    ]}
@app.post("/clients/delete")
def delete_client(
    payload: Dict[str, Any] = Body(...),
    user_id: str = Header(..., alias="X-User-Id"),
):
    """
    Delete one or more clients for the authenticated user.

    Accepts any of these shapes:
    - { broker: 'motilal'|'dhan', client_id: 'WOIE1286' }
    - { broker: 'motilal', userid: 'WOIE1286' }
    - { items: [ { broker:'motilal', client_id:'WOIE1286' }, { broker:'dhan', userid:'123456' } ] }
    - { broker:'motilal', userids:['WOIE1286','WOIE1284'] }

    Returns a summary with deleted & missing arrays.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing X-User-Id header")
    deleted, missing = [], []

    # unify into a list of {broker, client_id}
    items: List[Dict[str, str]] = []
    if "items" in payload and isinstance(payload["items"], list):
        items = payload["items"]
    elif "userids" in payload and isinstance(payload["userids"], list):
        broker = (_pick(payload.get("broker")) or "").lower()
        items = [{"broker": broker, "client_id": u} for u in payload["userids"]]
    else:
        items = [payload]

    for it in items:
        broker    = (_pick(it.get("broker")) or "").lower()
        client_id = _pick(it.get("client_id"), it.get("userid"))
        if not broker or not client_id:
            missing.append({"broker": broker, "client_id": client_id, "reason": "missing broker/client_id"})
            continue
        path = _user_client_path(user_id, broker, client_id)
        try:
            if os.path.exists(path):
                os.remove(path)
                # Remove from GitHub as well
                try:
                    rel_path = os.path.relpath(path, BASE_DIR).replace("\\", "/")
                    _github_file_delete(rel_path)
                except Exception:
                    pass
                deleted.append({"broker": broker, "client_id": client_id})
            else:
                missing.append({"broker": broker, "client_id": client_id, "reason": "not found"})
        except Exception as e:
            missing.append({"broker": broker, "client_id": client_id, "reason": str(e)})
    return {"success": True, "deleted": deleted, "missing": missing}
# 
# 
# @app.get("/debug/list_local_clients")
# def debug_local_clients():
#     result = {"motilal": [], "dhan": []}
#     for brk, folder in (("dhan", DHAN_DIR), ("motilal", MO_DIR)):
#         try:
#             for fn in os.listdir(folder):
#                 if fn.endswith(".json"):
#                     result[brk].append(fn)
#         except Exception as e:
#             result[brk].append(f"Error: {e}")
#     return result
# 
# 
# 
# @app.post("/add_group")
# def add_group(payload: Dict[str, Any] = Body(...)):
#     """
#     Save a group immediately. Minimal schema:
#       { name: str, multiplier: number, members: [{broker, userid}] }
# 
#     File is stored as ./data/groups/<id>.json where <id> is name (safe) or provided id.
#     """
#     name = _pick(payload.get("name"))
#     if not name:
#         raise HTTPException(status_code=400, detail="group 'name' is required")
# 
#     # allow caller to pass id; else use name
#     group_id = _pick(payload.get("id"), name)
#     try:
#         mult_raw = payload.get("multiplier", 1)
#         multiplier = float(mult_raw) if str(mult_raw).strip() else 1.0
#         if multiplier <= 0:
#             raise ValueError("multiplier must be > 0")
#     except Exception:
#         raise HTTPException(status_code=400, detail="invalid 'multiplier'")
# 
#     raw_members = payload.get("members") or []
#     members: List[Dict[str, str]] = []
#     for m in raw_members:
#         broker = (_pick((m or {}).get("broker")) or "").lower()
#         userid = _pick((m or {}).get("userid"), (m or {}).get("client_id"))
#         if not broker or not userid:
#             # skip malformed rows quietly
#             continue
#         members.append({"broker": broker, "userid": userid})
# 
#     if not members:
#         raise HTTPException(status_code=400, detail="at least one valid member is required")
# 
#     doc = {
#         "id": _safe(group_id),
#         "name": name,
#         "multiplier": multiplier,
#         "members": members,
#     }
# 
#     path = _group_path(doc["id"])
#     _save(path, doc)
#     return {"success": True, "group": doc}
# 
# @app.get("/groups")
# def get_groups():
#     """
#     List all saved groups.
#     Returns:
#       { "groups": [ { id, name, multiplier, members: [{broker, userid}, ...] } ] }
#     """
#     try:
#         items = _list_groups()  # uses ./data/groups/*.json
#         # Ensure a stable shape for the UI
#         groups = [{
#             "id": g.get("id"),
#             "name": g.get("name"),
#             "multiplier": g.get("multiplier", 1),
#             "members": g.get("members", []),
#         } for g in items]
#         return {"groups": groups}
#     except Exception as e:
#         return {"groups": [], "error": str(e)}
# 
# 
# @app.get("/get_groups")
# def get_groups_alias():
#     return get_groups()   # the /groups handler
# 
# @app.post("/edit_group")
# def edit_group(payload: Dict[str, Any] = Body(...)):
#     """
#     Update group fields. Accepts { id? | name, name?, multiplier?, members? }
#     Keeps file id stable (no rename); only updates content.
#     """
#     id_or_name = _pick(payload.get("id"), payload.get("name"))
#     if not id_or_name:
#         raise HTTPException(status_code=400, detail="group 'id' or 'name' is required")
# 
#     path = _find_group_path(id_or_name)
#     if not path:
#         raise HTTPException(status_code=404, detail="group not found")
# 
#     doc = _read_json(path) or {}
#     # name
#     if payload.get("name"):
#         doc["name"] = str(payload["name"]).strip()
# 
#     # multiplier
#     if "multiplier" in payload:
#         try:
#             m = float(payload.get("multiplier", 1))
#             if m <= 0:
#                 raise ValueError
#         except Exception:
#             raise HTTPException(status_code=400, detail="invalid 'multiplier'")
#         doc["multiplier"] = m
# 
#     # members
#     if "members" in payload:
#         raw = payload.get("members") or []
#         members: List[Dict[str, str]] = []
#         for m in raw:
#             b = (_pick((m or {}).get("broker")) or "").lower()
#             u = _pick((m or {}).get("userid"), (m or {}).get("client_id"))
#             if b and u:
#                 members.append({"broker": b, "userid": u})
#         if not members:
#             raise HTTPException(status_code=400, detail="at least one valid member is required")
#         doc["members"] = members
# 
#     # ensure id present in doc
#     doc["id"] = doc.get("id") or os.path.splitext(os.path.basename(path))[0]
# 
#     _save(path, doc)
#     return {"success": True, "group": doc}
# 
# @app.post("/delete_group")
# def delete_group(payload: Dict[str, Any] = Body(...)):
#     """
#     Delete groups by ids and/or names.
#     Accepts: { ids: [..], names: [..] }
#     """
#     ids = payload.get("ids") or []
#     names = payload.get("names") or []
#     targets = [str(x) for x in (ids + names)]
#     if not targets:
#         raise HTTPException(status_code=400, detail="provide 'ids' or 'names'")
# 
#     deleted: List[str] = []
#     for t in targets:
#         p = _find_group_path(t)
#         if p and os.path.exists(p):
#             try:
#                 os.remove(p)
#                 # replicate delete to GitHub
#                 try:
#                     rel_path = os.path.relpath(p, BASE_DIR).replace("\\", "/")
#                     _github_file_delete(rel_path)
#                 except Exception:
#                     pass
#                 deleted.append(os.path.splitext(os.path.basename(p))[0])
#             except Exception:
#                 # skip failures silently
#                 pass
# 
#     return {"success": True, "deleted": deleted}
# 
# @app.get("/list_copytrading_setups")
# def list_copytrading_setups():
#     """Return all saved copy-trading setups."""
#     items: List[Dict[str, Any]] = []
#     try:
#         for fn in os.listdir(COPY_ROOT):
#             if not fn.endswith(".json"):
#                 continue
#             path = os.path.join(COPY_ROOT, fn)
#             doc = _read_json(path)
#             if not isinstance(doc, dict):
#                 continue
#             # ensure minimal fields
#             doc["id"] = doc.get("id") or os.path.splitext(fn)[0]
#             doc["name"] = doc.get("name") or doc["id"]
#             items.append(doc)
#     except FileNotFoundError:
#         pass
#     items.sort(key=lambda d: (d.get("name") or "").lower())
#     return {"setups": items}
# 
# @app.post("/add_copy_setup")
# def add_copy_setup(payload=Body(...)):
#     return save_copytrading_setup(payload)
# 
# @app.post("/edit_copy_setup")
# def edit_copy_setup(payload=Body(...)):
#     return save_copytrading_setup(payload)
# 
# 
# @app.post("/enable_copy")
# def enable_copy(payload: Dict[str, Any] = Body(...)):
#     """Enable copy-trading for given setup ids/names."""
#     return _set_copy_enabled(payload, True)
# 
# @app.post("/disable_copy")
# def disable_copy(payload: Dict[str, Any] = Body(...)):
#     """Disable copy-trading for given setup ids/names."""
#     return _set_copy_enabled(payload, False)
# 
# @app.post("/save_copytrading_setup")
# def save_copytrading_setup(payload: Dict[str, Any] = Body(...)):
#     """
#     Upsert a copy-trading setup.
#     Accepts either UI or generic keys:
#       {
#         id?: str,
#         name|setup_name: str,
#         master|master_account: str,
#         children|child_accounts: [str|{userid|client_id|id|value|account}],
#         multipliers?: { child: number },
#         enabled?: bool
#       }
#     """
#     name   = _pick(payload.get("name"),   payload.get("setup_name"))
#     master = _pick(payload.get("master"), payload.get("master_account"))
#     children = _extract_children(payload.get("children") or payload.get("child_accounts") or [])
#     # remove master if present in children
#     children = [c for c in children if c != master]
# 
#     if not name or not master or not children:
#         raise HTTPException(status_code=400, detail="name, master, and children are required")
# 
#     multipliers = _build_multipliers(children, payload.get("multipliers"))
#     enabled = bool(payload.get("enabled", False))
# 
#     mode = "created"
#     doc: Dict[str, Any] = {}
# 
#     # resolve update path by id or (fallback) by name
#     setup_id = _pick(payload.get("id"))
#     path = None
#     if setup_id:
#         path = _find_copy_path(setup_id)
#     if not path:
#         # try by name
#         path = _find_copy_path(name)
# 
#     if path and os.path.exists(path):
#         # UPDATE
#         mode = "updated"
#         doc = _read_json(path) or {}
#         doc["name"] = name
#         doc["master"] = str(master)
#         doc["children"] = children
#         doc["multipliers"] = multipliers
#         if "enabled" in payload:
#             doc["enabled"] = enabled
#         doc["id"] = doc.get("id") or os.path.splitext(os.path.basename(path))[0]
#     else:
#         # CREATE
#         setup_id = setup_id or _unique_copy_id(name)
#         doc = {
#             "id": setup_id,
#             "name": name,
#             "master": str(master),
#             "children": children,
#             "multipliers": multipliers,
#             "enabled": enabled,
#         }
#         path = _copy_path(setup_id)
# 
#     _save(path, doc)
#     return {"success": True, "mode": mode, "setup": doc}
# 
# @app.post("/delete_copy_setup")
# def delete_copy_setup(payload: Dict[str, Any] = Body(...)):
#     """
#     Delete setups by ids and/or names.
#     Accepts: { ids: [..], names: [..], id?, name? }
#     """
#     ids = list(payload.get("ids") or [])
#     names = list(payload.get("names") or [])
#     if payload.get("id"):   ids.append(str(payload["id"]))
#     if payload.get("name"): names.append(str(payload["name"]))
# 
#     targets = [str(x) for x in (ids + names)]
#     if not targets:
#         raise HTTPException(status_code=400, detail="provide 'ids' or 'names'")
# 
#     deleted: list[str] = []
#     for t in targets:
#         p = _find_copy_path(t)
#         if p and os.path.exists(p):
#             try:
#                 os.remove(p)
#                 try:
#                     rel_path = os.path.relpath(p, BASE_DIR).replace("\\", "/")
#                     _github_file_delete(rel_path)
#                 except Exception:
#                     pass
#                 deleted.append(os.path.splitext(os.path.basename(p))[0])
#             except Exception:
#                 pass
# 
#     return {"success": True, "deleted": deleted}
# 
# # Optional compatibility alias if your UI ever calls this older name
# @app.post("/delete_copytrading_setup")
# def delete_copytrading_setup(payload: Dict[str, Any] = Body(...)):
#     return delete_copy_setup(payload)  # re-use the same logic
# 
# # put this helper near your other helpers
# def _guess_broker_from_order(order: Dict[str, Any]) -> str | None:
#     """
#     Decide broker using order_id shape first (safest), then fall back to name.
#     - Dhan orderId: digits only
#     - Motilal uniqueorderid: alphanumeric (letters present)
#     """
#     oid = str((order or {}).get("order_id", "")).strip()
#     if oid.isdigit():
#         return "dhan"
#     if any(c.isalpha() for c in oid):
#         return "motilal"
#     # fallback if unknown shape
#     return _broker_by_client_name((order or {}).get("name"))
# 
# 
# # ---- helper to locate which broker a name belongs to
# def _broker_by_client_name(name: str) -> str | None:
#     if not name:
#         return None
#     needle = str(name).strip().lower()
#     for brk, folder in (("dhan", DHAN_DIR), ("motilal", MO_DIR)):
#         try:
#             for fn in os.listdir(folder):
#                 if not fn.endswith('.json'):
#                     continue
#                 try:
#                     with open(os.path.join(folder, fn), 'r', encoding='utf-8') as f:
#                         d = json.load(f)
#                     nm = (d.get('name') or d.get('display_name') or '').strip().lower()
#                     if nm == needle:
#                         return brk
#                 except Exception:
#                     continue
#         except FileNotFoundError:
#             pass
#     return None
# 
@app.get('/get_orders')
def route_get_orders():
    from collections import OrderedDict
    buckets = OrderedDict({k: [] for k in STAT_KEYS})
    for brk in ('dhan','motilal'):
        try:
            mod = importlib.import_module('Broker_dhan' if brk=='dhan' else 'Broker_motilal')
            fn = getattr(mod, 'get_orders', None)
            if callable(fn):
                data = fn()
                if isinstance(data, dict):
                    for k in STAT_KEYS:
                        buckets[k].extend(data.get(k, []) or [])
        except Exception as e:
            print(f"[router] get_orders error for {brk}: {e}")
    return buckets



@app.post("/cancel_order")
def route_cancel_order(payload: Dict[str, Any] = Body(...)):
    orders = payload.get("orders", [])
    if not isinstance(orders, list) or not orders:
        raise HTTPException(status_code=400, detail="❌ No orders received for cancellation.")

    # --- bucket by broker using your working helper
    by_broker: Dict[str, List[Dict[str, Any]]] = {"dhan": [], "motilal": []}
    unknown: List[str] = []
    for od in orders:
        name = (od or {}).get("name", "")
        brk = _broker_by_client_name(name)
        if brk in by_broker:
            by_broker[brk].append(od)
        else:
            unknown.append(name or str(od))

    messages: List[str] = []

    # -------------------------
    # D H A N
    # -------------------------
    if by_broker["dhan"]:
        try:
            dh = importlib.import_module("Broker_dhan")

            # Prefer a batch API if the module provides one
            if hasattr(dh, "cancel_orders") and callable(getattr(dh, "cancel_orders")):
                res = dh.cancel_orders(by_broker["dhan"])
                if isinstance(res, list):
                    messages.extend([str(x) for x in res])
                elif isinstance(res, dict) and isinstance(res.get("message"), list):
                    messages.extend([str(x) for x in res["message"]])
                else:
                    messages.append(str(res))
            else:
                # Fallback: call single-order helper cancel_order_dhan(...)
                def _load_dhan_json(name: str) -> Optional[Dict[str, Any]]:
                    needle = (name or "").strip().lower()
                    try:
                        for fn in os.listdir(DHAN_DIR):
                            if not fn.endswith(".json"):
                                continue
                            path = os.path.join(DHAN_DIR, fn)
                            with open(path, "r", encoding="utf-8") as f:
                                cj = json.load(f)
                            nm = (cj.get("name") or cj.get("display_name") or "").strip().lower()
                            if nm == needle:
                                return cj
                    except FileNotFoundError:
                        pass
                    return None

                for od in by_broker["dhan"]:
                    name = od.get("name", "")
                    oid  = od.get("order_id", "")
                    cj   = _load_dhan_json(name)
                    if not cj or not oid:
                        messages.append(f"❌ Missing client JSON or order_id for {name}")
                        continue
                    try:
                        resp = dh.cancel_order_dhan(cj, oid)
                        ok = isinstance(resp, dict) and str(resp.get("status", "")).lower() == "success"
                        if ok:
                            messages.append(f"✅ Cancelled Order {oid} for {name}")
                        else:
                            err = (resp.get("message") if isinstance(resp, dict) else resp)
                            messages.append(f"❌ Failed to cancel Order {oid} for {name}: {err}")
                    except Exception as e:
                        messages.append(f"❌ dhan cancel failed for {name}: {e}")

        except Exception as e:
            messages.append(f"❌ dhan cancel failed: {e}")

    # -------------------------
    # M O T I L A L
    # -------------------------
    if by_broker["motilal"]:
        try:
            mo = importlib.import_module("Broker_motilal")
            if hasattr(mo, "cancel_orders") and callable(getattr(mo, "cancel_orders")):
                res = mo.cancel_orders(by_broker["motilal"])
                if isinstance(res, list):
                    messages.extend([str(x) for x in res])
                elif isinstance(res, dict) and isinstance(res.get("message"), list):
                    messages.extend([str(x) for x in res["message"]])
                else:
                    messages.append(str(res))
            else:
                # Very defensive fallback: try a per-order function if it exists
                for od in by_broker["motilal"]:
                    try:
                        if hasattr(mo, "cancel_order"):
                            r = mo.cancel_order({"orders": [od]})
                            if isinstance(r, dict) and isinstance(r.get("message"), list):
                                messages.extend([str(x) for x in r["message"]])
                            else:
                                messages.append(str(r))
                        else:
                            messages.append("❌ motilal cancel: no suitable function exported")
                    except Exception as e:
                        messages.append(f"❌ motilal cancel failed: {e}")
        except Exception as e:
            messages.append(f"❌ motilal cancel failed: {e}")

    # If nothing matched, keep the UI behaviour you expect
    if not by_broker["dhan"] and not by_broker["motilal"]:
        return {"message": ["No matching broker for the selected orders."]}

    if unknown:
        messages.append("ℹ️ Unknown broker for: " + ", ".join(sorted(set(unknown))))

    return {"message": messages}





@app.get("/get_positions")
def route_get_positions():
    """Merge positions from both brokers into {open:[...], closed:[...]}"""
    buckets = {"open": [], "closed": []}
    for brk in ("dhan", "motilal"):
        try:
            mod = importlib.import_module("Broker_dhan" if brk == "dhan" else "Broker_motilal")
            fn  = getattr(mod, "get_positions", None)
            if callable(fn):
                res = fn()
                if isinstance(res, dict):
                    buckets["open"].extend(res.get("open", []) or [])
                    buckets["closed"].extend(res.get("closed", []) or [])
        except Exception as e:
            print(f"[router] get_positions error for {brk}: {e}")
    return buckets

@app.post("/close_positions")
def route_close_positions(payload: Dict[str, Any] = Body(...)):
    """payload: { positions: [{ name, symbol }, ...] }"""
    items = payload.get("positions")
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="'positions' must be a list")

    # bucket by broker using name
    def _which_broker(name: str) -> str | None:
        if not name:
            return None
        needle = str(name).strip().lower()
        for brk, folder in (("dhan", DHAN_DIR), ("motilal", MO_DIR)):
            try:
                for fn in os.listdir(folder):
                    if not fn.endswith(".json"): continue
                    with open(os.path.join(folder, fn), "r", encoding="utf-8") as f:
                        d = json.load(f)
                    if (d.get("name") or d.get("display_name") or "").strip().lower() == needle:
                        return brk
            except FileNotFoundError:
                pass
        return None

    buckets = {"dhan": [], "motilal": []}
    for it in items:
        brk = _which_broker((it or {}).get("name"))
        if brk in buckets:
            buckets[brk].append(it)

    messages: List[str] = []
    for brk, rows in buckets.items():
        if not rows: continue
        try:
            mod = importlib.import_module("Broker_dhan" if brk == "dhan" else "Broker_motilal")
            fn  = getattr(mod, "close_positions", None)
            res = fn(rows) if callable(fn) else None
            if isinstance(res, list):
                messages.extend([str(x) for x in res])
            elif isinstance(res, dict):
                msgs = res.get("message") or res.get("messages") or []
                if isinstance(msgs, list): messages.extend([str(x) for x in msgs])
        except Exception as e:
            messages.append(f"❌ {brk} close_positions error: {e}")

    return {"message": messages}
@app.get("/get_holdings")
def route_get_holdings():
    buckets = {"holdings": [], "summary": []}
    for brk in ("dhan", "motilal"):
        try:
            mod = importlib.import_module("Broker_dhan" if brk == "dhan" else "Broker_motilal")
            fn  = getattr(mod, "get_holdings", None)
            if callable(fn):
                res = fn()
                if isinstance(res, dict):
                    buckets["holdings"].extend(res.get("holdings", []) or [])
                    buckets["summary"].extend(res.get("summary", []) or [])
        except Exception as e:
            print(f"[router] get_holdings error for {brk}: {e}")

    # <-- keep your existing return, but also cache for /get_summary
    global summary_data_global
    # key by client name so get_summary can do .values()
    summary_data_global = { (s.get("name") or f"client_{i}"): s
                            for i, s in enumerate(buckets["summary"])
                            if isinstance(s, dict) }

    return buckets

@app.get("/get_summary")
def get_summary():
    return {"summary": list(summary_data_global.values())}

def _safe_int(val, default=0):
    try:
        if val is None: 
            return default
        s = str(val).strip()
        if s == "":
            return default
        return int(float(s))
    except Exception:
        return default

def _pick_qty_for_client(ci: dict, per_client_qty: dict, default_qty: int) -> int:
    """Try several keys (id, name, trimmed name) to find a per-client qty."""
    if not isinstance(per_client_qty, dict):
        return default_qty
    keys = []
    # ids
    keys.append(str(ci.get("userid") or ci.get("client_id") or "").strip())
    # human names
    nm = (ci.get("name") or ci.get("display_name") or "").strip()
    if nm:
        keys.append(nm)
        # sometimes UI includes labels like "Edison : 1100922501"
        keys.append(nm.split(":")[0].strip())
    # first non-empty match wins
    for k in keys:
        if k and k in per_client_qty:
            q = _safe_int(per_client_qty[k], default=None)
            if q is not None:
                return q
    return default_qty


@app.post("/place_orders")
def route_place_orders(payload: Dict[str, Any] = Body(...)):
    import importlib, os, json, csv
    from typing import Optional, Dict, Any, List

    data = payload or {}

    # ------------------- robust symbol parsing -------------------
    raw_symbol = (data.get("symbol") or "").strip()  # "NSE|PNB EQ|110666|17000"
    explicit_id  = data.get("symbolId") or data.get("symbol_id") or data.get("security_id") or data.get("token")
    explicit_tok = data.get("symboltoken") or data.get("token")

    parts = [p.strip() for p in raw_symbol.split("|") if p is not None]
    exchange_from_symbol = parts[0] if len(parts) > 0 else ""
    stock_symbol         = parts[1] if len(parts) > 1 else ""
    security_id          = parts[2] if len(parts) > 2 else ""   # Dhan
    symboltoken          = parts[3] if len(parts) > 3 else ""   # Motilal

    if not security_id and explicit_id:
        security_id = str(explicit_id)
    if not symboltoken and explicit_tok:
        symboltoken = str(explicit_tok)

    # Optional backfills from local masters (if wired)
    lookup_dhan = globals().get("_lookup_security_id_sqlite")
    lookup_mo   = (
        globals().get("_lookup_symboltoken_sqlite")
        or globals().get("_lookup_motilal_token_sqlite")
        or globals().get("_lookup_symboltoken_csv")
    )
    exchange_val = (data.get("exchange") or exchange_from_symbol or "NSE").upper()
    if not security_id and callable(lookup_dhan) and stock_symbol:
        try:
            found = lookup_dhan(exchange_val, stock_symbol)
            if found: security_id = str(found)
        except Exception:
            pass
    if not symboltoken and callable(lookup_mo) and stock_symbol:
        try:
            found = lookup_mo(exchange_val, stock_symbol)
            if found: symboltoken = str(found)
        except Exception:
            pass

    # ------------------- common UI fields -------------------
    groupacc        = bool(data.get("groupacc", False))
    groups          = data.get("groups", []) or []
    clients         = data.get("clients", []) or []
    diffQty         = bool(data.get("diffQty", False))
    multiplier_flag = bool(data.get("multiplier", False))
    qtySelection    = data.get("qtySelection", "manual")
    quantityinlot   = int(data.get("quantityinlot", 0) or 0)
    perClientQty    = data.get("perClientQty", {}) or {}
    perGroupQty     = data.get("perGroupQty", {}) or {}
    action          = (data.get("action") or "").upper()
    ordertype       = (data.get("ordertype") or "").upper()
    producttype     = data.get("producttype") or ""
    orderduration   = data.get("orderduration") or "DAY"
    price           = float(data.get("price", 0) or 0)
    triggerprice    = float(data.get("triggerprice", 0) or 0)
    disclosedqty    = int(data.get("disclosedquantity", 0) or 0)
    amoorder        = data.get("amoorder", "N")
    correlation_id  = data.get("correlationId", "") or data.get("correlation_id", "")

    if ordertype == "LIMIT" and price <= 0:
        raise HTTPException(status_code=400, detail="Price must be > 0 for LIMIT orders.")
    if "SL" in ordertype and triggerprice <= 0:
        raise HTTPException(status_code=400, detail="Trigger price is required for SL/SL-M orders.")

    # ------------------- client index (userid -> broker/name/json) -------------------
    BASE_DIR   = os.path.abspath(os.environ.get("DATA_DIR", "./data"))
    DHAN_DIR   = os.path.join(BASE_DIR, "clients", "dhan")
    MO_DIR     = os.path.join(BASE_DIR, "clients", "motilal")
    GROUPS_DIR = os.path.join(BASE_DIR, "groups")

    def _index_clients() -> Dict[str, Dict[str, Any]]:
        idx: Dict[str, Dict[str, Any]] = {}
        for brk, folder in (("dhan", DHAN_DIR), ("motilal", MO_DIR)):
            try:
                for fn in os.listdir(folder):
                    if not fn.endswith(".json"):
                        continue
                    with open(os.path.join(folder, fn), "r", encoding="utf-8") as f:
                        cj = json.load(f)
                    uid = str(cj.get("userid") or cj.get("client_id") or "").strip()
                    if uid:
                        idx[uid] = {
                            "broker": brk,
                            "json": cj,
                            "name": cj.get("name") or cj.get("display_name") or uid,
                        }
            except FileNotFoundError:
                continue
        return idx

    client_index = _index_clients()

    # ------------------- qty calc helper -------------------
    def _auto_qty_fallback(_client_id: str, _price: float) -> int:
        return quantityinlot

    # ------------------- min-qty lookup helpers (CSV + optional globals) -------------------
    def _normalize_col(name: str) -> str:
        # "Security ID" -> "securityid", "Min qty" -> "minqty"
        return "".join(ch for ch in str(name).lower() if ch.isalnum())

    def _get_min_qty_map() -> Dict[str, int]:
        """Cache CSV -> {security_id: min_qty} on first call. Robust to header variants."""
        if hasattr(_get_min_qty_map, "_cache"):
            return _get_min_qty_map._cache  # type: ignore[attr-defined]

        cache: Dict[str, int] = {}

        masters  = os.path.join(BASE_DIR, "masters")
        candidates = [
            os.environ.get("SECURITY_MIN_QTY_CSV"),
            os.path.join(masters, "security_id_min_qty.csv"),
            os.path.join(masters, "security_id.csv"),
            os.path.join(BASE_DIR, "security_id_min_qty.csv"),
            os.path.join(BASE_DIR, "security_id.csv"),
            os.path.join(BASE_DIR, "security_master.csv"),
            os.path.join(BASE_DIR, "security_ids.csv"),
        ]
        candidates = [p for p in candidates if p]

        for path in candidates:
            try:
                if not os.path.exists(path):
                    continue
                with open(path, "r", encoding="utf-8") as f:
                    rdr = csv.DictReader(f)
                    for row in rdr:
                        nrow = { _normalize_col(k): v for k, v in row.items() }
                        sid = (
                            nrow.get("securityid") or nrow.get("security_id")
                            or nrow.get("id") or nrow.get("token")
                            or nrow.get("symboltoken") or ""
                        )
                        sid = str(sid).strip()
                        if not sid:
                            continue
                        raw_mq = (
                            nrow.get("minqty") or nrow.get("minquantity")
                            or nrow.get("lotsize") or nrow.get("tradinglot")
                            or nrow.get("marketlot") or nrow.get("minorderqty")
                            or "1"
                        )
                        try:
                            cache[sid] = max(1, int(float(str(raw_mq).strip())))
                        except Exception:
                            cache[sid] = 1
                break
            except Exception:
                continue

        _get_min_qty_map._cache = cache  # type: ignore[attr-defined]
        return cache

    def _min_qty_for(security_id_val: str) -> int:
        """Try user-provided helpers first, then CSV map, default=1."""
        if not security_id_val:
            return 1
        for fname in ("_lookup_min_qty_sqlite", "_lookup_min_qty", "_lookup_min_qty_csv"):
            fn = globals().get(fname)
            if callable(fn):
                try:
                    v = fn(str(security_id_val))
                    if v:
                        return max(1, int(v))
                except Exception:
                    pass
        return int(_get_min_qty_map().get(str(security_id_val), 1))

    # ------------------- make one order row -------------------
    def _build_order(client_id: str, qty: int, tag: Optional[str]) -> Dict[str, Any]:
        ci = client_index.get(str(client_id))
        if not ci:
            return {"_skip": True, "reason": "client_not_found", "client_id": client_id}
        return {
            "client_id": str(client_id),
            "name": ci["name"],
            "broker": ci["broker"],
            "action": action,
            "ordertype": ordertype,
            "producttype": producttype,
            "orderduration": orderduration,
            "exchange": exchange_val,
            "price": price,
            "triggerprice": triggerprice,
            "disclosedquantity": disclosedqty,
            "amoorder": amoorder,
            "qty": int(qty),  # front-end qty
            "tag": tag or "",
            "correlation_id": correlation_id,
            "symbol": raw_symbol,
            "security_id": str(security_id or ""),   # Dhan
            "symboltoken": str(symboltoken or ""),   # Motilal
            "stock_symbol": stock_symbol,
        }

    # ------------------- expand to per-client orders -------------------
    per_client_orders: List[Dict[str, Any]] = []

    if groupacc:
        def _member_ids(doc: Dict[str, Any]) -> List[str]:
            out: List[str] = []
            raw = (doc.get("members") or doc.get("clients") or [])
            for m in raw:
                if isinstance(m, dict):
                    uid = (m.get("userid") or m.get("client_id") or m.get("id") or "").strip()
                else:
                    uid = str(m).strip()
                if uid and uid not in out:
                    out.append(uid)
            return out

        for gsel in groups:
            gp = (globals().get("_find_group_path")(gsel)
                  or os.path.join(GROUPS_DIR, f"{str(gsel).replace(' ', '_')}.json"))
            if not gp or not os.path.exists(gp):
                per_client_orders.append({"_skip": True, "reason": f"group_file_missing:{gsel}"})
                continue

            try:
                with open(gp, "r", encoding="utf-8") as f:
                    gdoc = json.load(f) or {}
            except Exception:
                per_client_orders.append({"_skip": True, "reason": f"group_file_bad:{gsel}"})
                continue

            gname = gdoc.get("name") or gdoc.get("id") or str(gsel)
            gkey  = gdoc.get("id") or gname
            members = _member_ids(gdoc)
            group_multiplier = int(gdoc.get("multiplier", 1) or 1)

            for client_id in members:
                if qtySelection == "auto":
                    q = _auto_qty_fallback(str(client_id), price)
                elif diffQty:
                    q = int((perGroupQty.get(gkey) or perGroupQty.get(gname) or 0) or 0)
                elif multiplier_flag:
                    q = quantityinlot * group_multiplier
                else:
                    q = quantityinlot
                per_client_orders.append(_build_order(str(client_id), q, gname))
    else:
        for client_id in clients:
            if qtySelection == "auto":
                q = _auto_qty_fallback(str(client_id), price)
            elif diffQty:
                q = int(perClientQty.get(str(client_id), 0) or 0)
            else:
                q = quantityinlot
            per_client_orders.append(_build_order(str(client_id), q, None))

    # ------------------- bucket by broker -------------------
    by_broker: Dict[str, List[Dict[str, Any]]] = {"dhan": [], "motilal": []}
    skipped: List[Dict[str, Any]] = []
    for od in per_client_orders:
        if od.get("_skip"):
            skipped.append(od)
            continue
        brk = od.get("broker")
        if brk in by_broker:
            by_broker[brk].append(od)

    # ------------------- DHAN: multiply qty by min_qty -------------------
    if by_broker.get("dhan"):
        for od in by_broker["dhan"]:
            try:
                sid = od.get("security_id") or ""
                minq = _min_qty_for(sid) if sid else 1
                old_q = int(od.get("qty", 0))
                new_q = old_q * max(1, int(minq))
                od["qty"] = new_q
                print(f"[router] DHAN lot-size applied: sid={sid} min_qty={minq} qty:{old_q} -> {new_q}")
            except Exception:
                od["qty"] = int(od.get("qty", 0))

    # ------------------- print & dispatch -------------------
    try:
        if by_broker.get("dhan"):
            print(f"[router] DHAN orders ({len(by_broker['dhan'])}) ->")
            print(json.dumps(by_broker["dhan"], indent=2))
        if by_broker.get("motilal"):
            print(f"[router] MOTILAL orders ({len(by_broker['motilal'])}) ->")
            print(json.dumps(by_broker["motilal"], indent=2))
    except Exception:
        pass

    results: Dict[str, Any] = {"skipped": skipped}
    for brk in ("dhan", "motilal"):
        lst = by_broker.get(brk, [])
        if not lst:
            continue
        try:
            print(f"[router] dispatching {len(lst)} orders to {brk}...")
            modname = "Broker_dhan" if brk == "dhan" else "Broker_motilal"
            mod = importlib.import_module(modname)
            try:
                mod = importlib.reload(mod)
            except Exception:
                pass
            fn = getattr(mod, "place_orders", None)
            res = fn(lst) if callable(fn) else {"status": "error", "message": "place_orders not implemented"}
        except Exception as e:
            res = {"status": "error", "message": str(e)}
        results[brk] = res

    return {"status": "completed", "result": results}

# Backward-compatibility for UIs posting to /place_order
@app.post("/place_order")
def route_place_order_compat(payload: Dict[str, Any] = Body(...)):
    return route_place_orders(payload)

@app.post("/modify_order")
def route_modify_order(payload: Dict[str, Any] = Body(...)):
    """
    Modify pending orders (Dhan + Motilal).

    Accepts either:
      { "orders":[{...},{...}], ... }  OR  { "order":{...}, ... }

    Fixes:
      - No empty strings sent to Dhan (quantity/price/trigger/disclosedQuantity).
      - Fills missing quantity from current pending order snapshot.
      - Sends Dhan orderType as proper enum.
    """
    import importlib, json, os

    # ---------- tiny utils ----------
    def _to_int_or_none(x):
        try:
            s = str(x).strip()
            return None if s == "" else int(float(s))
        except Exception:
            return None

    def _to_float_or_none(x):
        try:
            s = str(x).strip()
            return None if s == "" else float(s)
        except Exception:
            return None

    def _map_ui_to_dhan(ui: str | None) -> str | None:
        if not ui: return None
        u = ui.upper().replace("-", "_")
        m = {
            "LIMIT": "LIMIT",
            "MARKET": "MARKET",
            "STOPLOSS": "STOP_LOSS",
            "SL_LIMIT": "STOP_LOSS",
            "SL": "STOP_LOSS",
            "STOP_LOSS": "STOP_LOSS",
            "SL_MARKET": "STOP_LOSS_MARKET",
            "STOPLOSS_MARKET": "STOP_LOSS_MARKET",
            "STOP_LOSS_MARKET": "STOP_LOSS_MARKET",
            "NO_CHANGE": None, "": None
        }
        return m.get(u, None)

    def _guess_from_values(price, trig) -> str:
        has_p = price is not None and str(price) != ""
        has_t = trig  is not None and str(trig)  != ""
        if has_t and has_p:  return "STOP_LOSS"         # SL-L
        if has_t and not has_p: return "STOP_LOSS_MARKET"  # SL-M
        if has_p and not has_t: return "LIMIT"
        return "MARKET"

    def _guess_broker_from_order(od: Dict[str, Any]) -> str | None:
        oid = str((od or {}).get("order_id") or (od or {}).get("orderId") or "").strip()
        if oid.isdigit(): return "dhan"
        if any(c.isalpha() for c in oid): return "motilal"
        return _broker_by_client_name((od or {}).get("name"))

    # ----- try to fetch current order snapshot from broker (for quantity/defaults)
    def _fetch_dhan_order_snapshot(order_id: str) -> dict | None:
        try:
            dh = importlib.import_module("Broker_dhan")
            fn = getattr(dh, "get_orders", None)
            if not callable(fn):
                return None
            data = fn() or {}
            for key in ("pending", "traded", "rejected", "cancelled", "others"):
                for row in (data.get(key) or []):
                    if str(row.get("order_id") or row.get("orderId") or "") == str(order_id):
                        return row
        except Exception:
            return None
        return None

    def _snap_qty(s: dict | None) -> int | None:
        if not isinstance(s, dict): return None
        for k in ("quantity", "qty", "order_qty", "orderQty", "orderQuantity", "quantityPlaced"):
            v = s.get(k)
            iv = _to_int_or_none(v)
            if iv and iv > 0: return iv
        # very last resort: pending + traded
        p = _to_int_or_none(s.get("pendingQuantity"))
        t = _to_int_or_none(s.get("tradedQuantity"))
        if p or t:
            total = (p or 0) + (t or 0)
            return total if total > 0 else None
        return None

    def _snap_validity(s: dict | None) -> str | None:
        if not isinstance(s, dict): return None
        v = (s.get("validity") or s.get("timeForce") or "").upper()
        return v or None

    # ---------- normalize input ----------
    orders = payload.get("orders")
    if not orders and payload.get("order"):
        orders = [payload["order"]]
    if not isinstance(orders, list) or not orders:
        raise HTTPException(status_code=400, detail="No orders provided.")

    qty_default  = _to_int_or_none(payload.get("quantity"))
    prc_default  = _to_float_or_none(payload.get("price"))
    trg_default  = _to_float_or_none(payload.get("triggerprice") or payload.get("trig_price"))
    ot_default   = (payload.get("orderType") or payload.get("ordertype") or "NO_CHANGE").upper()
    validity_in  = (payload.get("validity") or payload.get("timeForce") or "DAY").upper()

    by_broker: Dict[str, List[Dict[str, Any]]] = {"dhan": [], "motilal": []}
    skipped: List[str] = []

    # ---------- build broker buckets ----------
    for od in orders:
        name = (od or {}).get("name", "")
        oid  = str((od or {}).get("order_id") or (od or {}).get("orderId") or "").strip()
        if not oid:
            skipped.append(f"{name or '<unknown>'}: missing order_id")
            continue

        brk = _guess_broker_from_order(od)
        if brk not in by_broker:
            skipped.append(f"{name} ({oid}): unknown broker")
            continue

        q   = _to_int_or_none(od.get("quantity"));             q   = q   if q   is not None else qty_default
        p   = _to_float_or_none(od.get("price"));              p   = p   if p   is not None else prc_default
        trg = _to_float_or_none(od.get("triggerprice") or od.get("triggerPrice"))
        trg = trg if trg is not None else trg_default

        ot_ui    = (od.get("orderType") or od.get("ordertype") or ot_default or "").upper()
        ot_dhan  = _map_ui_to_dhan(ot_ui)
        ot_final = ot_dhan or _guess_from_values(p, trg)

        # fetch snapshot for dhan if we miss critical fields
        snap = None
        if brk == "dhan" and (q is None or not validity_in or ot_ui in ("", "NO_CHANGE")):
            snap = _fetch_dhan_order_snapshot(oid)

        if q is None and brk == "dhan":
            q = _snap_qty(snap)
        if not validity_in and brk == "dhan":
            validity = _snap_validity(snap) or "DAY"
        else:
            validity = validity_in or "DAY"

        # explicit validations (only for explicit changes)
        if ot_dhan:
            if ot_dhan == "LIMIT" and (p is None or p <= 0):
                skipped.append(f"{name} ({oid}): LIMIT requires Price > 0")
                continue
            if ot_dhan == "STOP_LOSS" and ((p is None or p <= 0) or (trg is None or trg <= 0)):
                skipped.append(f"{name} ({oid}): STOPLOSS requires both Price and Trigger > 0")
                continue
            if ot_dhan == "STOP_LOSS_MARKET" and (trg is None or trg <= 0):
                skipped.append(f"{name} ({oid}): SL-MARKET requires Trigger > 0")
                continue

        row_common = {
            "name": name,
            "order_id": oid,
            "validity": validity,
            # keep floats as floats; ints as ints
            "quantity": q,                     # if None, we'll still pass numeric fallback for Dhan
            "price": p,
            "triggerPrice": trg,
        }

        if brk == "dhan":
            # Dhan needs a concrete enum; never send "NO_CHANGE"
            row_dhan = {
                **row_common,
                "orderType": ot_final,         # LIMIT | MARKET | STOP_LOSS | STOP_LOSS_MARKET
                "disclosedQuantity": 0,        # never empty string
            }
            # attach client json
            # local file scan (same as in your previous version)
            def _load_client_json_dhan(name_: str) -> Dict[str, Any] | None:
                needle = (name_ or "").strip().lower()
                try:
                    for fn in os.listdir(DHAN_DIR):
                        if not fn.endswith(".json"): continue
                        pth = os.path.join(DHAN_DIR, fn)
                        with open(pth, "r", encoding="utf-8") as f:
                            cj = json.load(f)
                        nm = (cj.get("name") or cj.get("display_name") or "").strip().lower()
                        if nm == needle:
                            return cj
                except FileNotFoundError:
                    return None
                except Exception:
                    return None
                return None

            row_dhan["_client_json"] = _load_client_json_dhan(name) or {}
            # If quantity is STILL None, use 0 (better than ""), Dhan ignores unchanged fields server-side.
            if row_dhan["quantity"] is None:
                row_dhan["quantity"] = 0
            by_broker["dhan"].append(row_dhan)
        else:
            # Motilal keeps UI word; broker module will map
            row_mo = {**row_common, "orderType": ot_ui or "NO_CHANGE"}
            by_broker["motilal"].append(row_mo)

    # ---------- logs ----------
    try:
        print("\n[/modify_order] INBOUND =>")
        print(json.dumps(payload, indent=2, default=str))
        print("\n[/modify_order] DHAN bucket =>")
        print(json.dumps(by_broker["dhan"], indent=2, default=str))
        print("\n[/modify_order] MOTILAL bucket =>")
        print(json.dumps(by_broker["motilal"], indent=2, default=str))
        if skipped:
            print("\n[/modify_order] SKIPPED =>")
            print(json.dumps(skipped, indent=2, default=str))
    except Exception:
        pass

    # ---------- dispatch ----------
    messages: List[str] = []
    if skipped:
        messages.extend([f"ℹ️ {s}" for s in skipped])

    # Dhan
    if by_broker["dhan"]:
        try:
            dh = importlib.import_module("Broker_dhan")
            res = None
            if hasattr(dh, "modify_orders") and callable(getattr(dh, "modify_orders")):
                res = dh.modify_orders(by_broker["dhan"])
            elif hasattr(dh, "Broker_dhan"):
                res = getattr(dh, "Broker_dhan")().modify_orders(by_broker["dhan"])
            else:
                messages.append("❌ Broker_dhan.modify_orders not implemented")

            try:
                print("\n[/modify_order] DHAN RESP =>")
                print(json.dumps(res, indent=2, default=str))
            except Exception:
                pass

            if isinstance(res, dict) and isinstance(res.get("message"), list):
                messages.extend([str(x) for x in res["message"]])
            elif res is not None:
                messages.append(str(res))
        except Exception as e:
            messages.append(f"❌ dhan modify failed: {e}")

    # Motilal
    if by_broker["motilal"]:
        try:
            mo = importlib.import_module("Broker_motilal")
            if hasattr(mo, "modify_orders") and callable(getattr(mo, "modify_orders")):
                res = mo.modify_orders(by_broker["motilal"])
                try:
                    print("\n[/modify_order] MOTILAL RESP =>")
                    print(json.dumps(res, indent=2, default=str))
                except Exception:
                    pass
                if isinstance(res, dict) and isinstance(res.get("message"), list):
                    messages.extend([str(x) for x in res["message"]])
                else:
                    messages.append(str(res))
            else:
                messages.append("❌ Broker_motilal.modify_orders not implemented")
        except Exception as e:
            messages.append(f"❌ motilal modify failed: {e}")

    try:
        print("\n[/modify_order] OUT MESSAGES =>")
        print(json.dumps(messages, indent=2, default=str))
    except Exception:
        print(messages)

    return {"message": messages}
    
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("MultiBroker_Router:app", host="127.0.0.1", port=5001, reload=False)







# ------------------ Groups API (enabled) ------------------

@app.get("/groups")
def get_groups():
    """Return all groups."""
    return {"groups": _list_groups()}


@app.get("/get_groups")
def get_groups_legacy():
    return get_groups()


@app.post("/add_group")
def add_group(payload: Dict[str, Any] = Body(...)):
    name = _pick(payload.get("name"))
    if not name:
        raise HTTPException(status_code=400, detail="Group name is required")
    gid = _pick(payload.get("id")) or name
    doc = {
        "id": gid,
        "name": name,
        "multiplier": payload.get("multiplier", 1),
        "members": payload.get("members", []),
        "updated_at": datetime.utcnow().isoformat(),
    }
    path = _group_path(gid)
    _save(path, doc)
    return {"success": True, "group": doc}


@app.post("/edit_group")
def edit_group(payload: Dict[str, Any] = Body(...)):
    return add_group(payload)


@app.post("/delete_group")
def delete_group(payload: Dict[str, Any] = Body(...)):
    gid = _pick(payload.get("id")) or _pick(payload.get("name"))
    if not gid:
        raise HTTPException(status_code=400, detail="Group id/name is required")
    path = _group_path(gid)
    _delete(path)
    return {"success": True}

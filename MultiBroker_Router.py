"""
A FastAPI router for a multi‑user Motilal trading system.

This router exposes endpoints for managing Motilal client credentials, groups and
copy‑trading setups.  It removes all Dhan‑specific logic from the original
multi‑broker code and introduces per‑user storage under the ``data/users``
directory.  All saved JSON documents are mirrored to a GitHub repository when
the appropriate environment variables are configured (``GITHUB_TOKEN``,
``GITHUB_REPO_OWNER``, ``GITHUB_REPO_NAME`` and optionally ``GITHUB_BRANCH``).

Key differences from the single‑user, multi‑broker implementation:

* Only the Motilal broker is supported; references to Dhan have been removed.
* Client files are stored under ``data/users/<user>/clients/motilal/<client_id>.json``.
* Group and copy‑trading setups are stored under ``data/groups`` and
  ``data/copy_setups`` respectively.  These are shared across all users, but
  could be extended to include per‑user namespaces if needed.
* A background login task is triggered when saving a client.  It uses
  ``Broker_motilal.login`` if available and updates the ``session_active`` flag
  accordingly.

To enable GitHub persistence set the following environment variables:

* ``GITHUB_TOKEN`` – a GitHub personal access token with repo write access.
* ``GITHUB_REPO_OWNER`` – the owner of the repository (user or org).
* ``GITHUB_REPO_NAME`` – the name of the repository.
* ``GITHUB_BRANCH`` (optional) – the branch to write to; defaults to ``main``.

If any of the required GitHub variables are missing the router will operate
locally and emit log messages rather than attempting to upload files.
"""

from __future__ import annotations

import base64
import importlib
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import requests
from fastapi import (BackgroundTasks, Body, FastAPI, HTTPException, Header,
                     Response)
from fastapi.middleware.cors import CORSMiddleware

###############################################################################
# Additional imports and globals for Motilal trading endpoints
#
# The single‑user CT_FastAPI implementation exposed a rich set of order‑ and
# portfolio‑related routes (e.g. placing orders, fetching open orders,
# positions, holdings and closing positions).  Those helpers rely on
# broker‑specific modules such as ``Broker_motilal`` to perform the actual
# API calls.  To provide equivalent functionality in this multi‑user router
# we import a handful of standard libraries up front and initialise a few
# module‑level variables.  These include small utilities for safe integer
# parsing and quantity selection as well as a cache for per‑client summary
# data.  These helpers are defined here rather than inline in each route
# handler for clarity and to mirror the structure of the original code.

import importlib
import csv
import logging
import math
import threading
from collections import OrderedDict

# --- Globals for positions and holdings summary (motilal only) ---
# position_meta is used by the close_position/convert_position logic to look
# up metadata (exchange, symboltoken, product type) for a given client and
# symbol.  summary_data_global caches account summaries for /get_summary.
position_meta: Dict[tuple, Dict[str, Any]] = {}
summary_data_global: Dict[str, Dict[str, Any]] = {}


try:
    # Optional authentication router.  If absent the import will fail quietly.
    from auth.auth_router import router as auth_router  # type: ignore
except Exception:
    auth_router = None  # type: ignore

__all__ = [
    "app",
]


###############################################################################
# FastAPI app setup
###############################################################################

# Create the FastAPI app
app = FastAPI(title="Motilal Multi‑User Router")

# Configure CORS to allow the deployed frontend origins and wildcard fallback
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        # Replace or extend these origins with your deployed front‑end URLs
        "https://multibroker-trader-multiuser.vercel.app",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount optional authentication router at /auth
if auth_router is not None:
    app.include_router(auth_router)


###############################################################################
# Helpers for safe strings and value selection
###############################################################################

def _safe(s: str | None) -> str:
    """
    Sanitize a string for use in file paths.  Replaces spaces with
    underscores and removes any character that is not alphanumeric, an underscore
    or a hyphen.

    Parameters
    ----------
    s: str | None
        Input string.

    Returns
    -------
    str
        Sanitized string.
    """
    s = (s or "").strip().replace(" ", "_")
    return "".join(ch for ch in s if ch.isalnum() or ch in ("_", "-"))


def _pick(*vals: Any) -> str:
    """
    Return the first non‑empty, non‑None value from a sequence.  Values are
    converted to strings and stripped of whitespace.  Useful for falling back
    through multiple candidate keys (e.g. ``client_id``, ``userid``).

    Parameters
    ----------
    *vals: Any
        Candidate values.

    Returns
    -------
    str
        The first truthy string or an empty string if none found.
    """
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s
    return ""


###############################################################################
# Filesystem and GitHub configuration
###############################################################################

# Base directory for all data.  Use DATA_DIR env var or default to ./data.
BASE_DIR = os.path.abspath(os.environ.get("DATA_DIR", "./data"))

# Per‑user storage root: data/users/<user>/clients/motilal
USERS_ROOT = os.path.join(BASE_DIR, "users")
os.makedirs(USERS_ROOT, exist_ok=True)

# Group storage root: data/groups
GROUPS_ROOT = os.path.join(BASE_DIR, "groups")
os.makedirs(GROUPS_ROOT, exist_ok=True)

# Copy‑trading setups root: data/copy_setups
COPY_ROOT = os.path.join(BASE_DIR, "copy_setups")
os.makedirs(COPY_ROOT, exist_ok=True)

# GitHub environment variables
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "").strip()
GITHUB_REPO_OWNER = os.environ.get("GITHUB_REPO_OWNER", "").strip()
GITHUB_REPO_NAME = os.environ.get("GITHUB_REPO_NAME", "").strip()
GITHUB_BRANCH = (os.environ.get("GITHUB_BRANCH", "main") or "main").strip()


def _github_enabled() -> bool:
    """
    Determine whether GitHub persistence is enabled.  If all required
    environment variables are provided then writes and deletes are mirrored to
    the configured repository; otherwise operations are local only.
    """
    return bool(GITHUB_TOKEN and GITHUB_REPO_OWNER and GITHUB_REPO_NAME)


def _gh_headers() -> Dict[str, str]:
    """
    Build HTTP headers for GitHub API requests.  The Authorization header is
    omitted if no token is set.
    """
    h = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "motilal-router",
    }
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h


def _gh_contents_url(path_in_repo: str) -> str:
    """
    Construct the GitHub API URL for a given repository path.  Prepends the
    repository owner/name and ensures forward slashes are used.
    """
    return (
        f"https://api.github.com/repos/{GITHUB_REPO_OWNER}/{GITHUB_REPO_NAME}/contents/{path_in_repo}"
    )


def _github_file_write(rel_path: str, content: str) -> None:
    """
    Write or update a file in the GitHub repository under the ``data/`` prefix.
    The function first checks if the file already exists to obtain its SHA, then
    performs a PUT request with the base64‑encoded content.  Errors are
    propagated as runtime exceptions.

    Parameters
    ----------
    rel_path: str
        Path relative to the data directory, e.g. ``users/alice/clients/motilal/abc.json``.

    content: str
        Raw JSON string to be encoded and written.
    """
    if not _github_enabled():
        print(f"[GITHUB_DISABLED] skip write: {rel_path}")
        return
    # Prepend "data/" and normalise separators
    path_in_repo = ("data/" + rel_path.lstrip("/")).replace("\\", "/")
    url = _gh_contents_url(path_in_repo)
    # Check if file exists to obtain SHA
    sha: Optional[str] = None
    try:
        r0 = requests.get(url, headers=_gh_headers(), params={"ref": GITHUB_BRANCH}, timeout=20)
        if r0.status_code == 200:
            sha = (r0.json() or {}).get("sha")
    except Exception as e:
        print(f"[GITHUB] sha lookup failed (will try create): {e}")
    # Build payload
    payload: Dict[str, Any] = {
        "message": f"update {path_in_repo}",
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    # Perform write
    r = requests.put(url, headers=_gh_headers(), json=payload, timeout=30)
    if r.status_code not in (200, 201):
        raise RuntimeError(f"GitHub write failed {r.status_code}: {r.text[:300]}")
    print(f"[GITHUB_OK] wrote: {path_in_repo}")


def _github_file_delete(rel_path: str) -> None:
    """
    Delete a file from the GitHub repository under the ``data/`` prefix.  If
    the file does not exist or GitHub is disabled the function returns
    silently.

    Parameters
    ----------
    rel_path: str
        Path relative to the data directory.
    """
    if not _github_enabled():
        print(f"[GITHUB_DISABLED] skip delete: {rel_path}")
        return
    path_in_repo = ("data/" + rel_path.lstrip("/")).replace("\\", "/")
    url = _gh_contents_url(path_in_repo)
    # Retrieve SHA for deletion
    try:
        r0 = requests.get(url, headers=_gh_headers(), params={"ref": GITHUB_BRANCH}, timeout=20)
    except Exception as e:
        print(f"[GITHUB] delete sha lookup failed: {e}")
        return
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


def _save(path: str, data: Dict[str, Any]) -> None:
    """
    Write a JSON document to disk and mirror it to GitHub.  The parent
    directory is created if it does not exist.

    Parameters
    ----------
    path: str
        Absolute filesystem path.
    data: Dict[str, Any]
        JSON‑serialisable dictionary.
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)
    try:
        rel_path = os.path.relpath(path, BASE_DIR).replace("\\", "/")
        _github_file_write(rel_path, json.dumps(data, indent=4))
    except Exception as e:
        print(f"[GITHUB_ERR] {e}")


def _read_json(path: str) -> Dict[str, Any]:
    """
    Read and decode a JSON file from disk.  Returns an empty dict on error.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


###############################################################################
# Per‑user client path helpers
###############################################################################

def _user_clients_root(user_id: str) -> str:
    """
    Compute the absolute path to a user's client directory:
    ``data/users/<user>/clients``.
    """
    safe_user = _safe(user_id)
    return os.path.join(USERS_ROOT, safe_user, "clients")


def _user_client_path(user_id: str, broker: str, client_id: str) -> str:
    """
    Compute the absolute path to a specific client's JSON file for a given
    broker.  Only the Motilal broker is supported.  The path has the form
    ``data/users/<user>/clients/motilal/<client_id>.json``.
    """
    safe_user = _safe(user_id)
    folder = os.path.join(USERS_ROOT, safe_user, "clients", _safe(broker))
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, f"{_safe(client_id)}.json")


###############################################################################
# Group and copy‑trading path helpers
###############################################################################

def _group_path(group_id_or_name: str) -> str:
    """
    Compute the absolute path to a group JSON file.  The id or name is
    sanitised via :func:`_safe` before being used as the filename.
    """
    return os.path.join(GROUPS_ROOT, f"{_safe(group_id_or_name)}.json")


def _copy_path(setup_id: str) -> str:
    """
    Compute the absolute path to a copy‑trading setup JSON file.  The setup
    id is sanitised via :func:`_safe` before being used as the filename.
    """
    return os.path.join(COPY_ROOT, f"{_safe(setup_id)}.json")


def _find_copy_path(id_or_name: str | None) -> Optional[str]:
    """
    Locate a copy‑trading setup by id (filename) or by name (case‑insensitive).
    Returns the absolute path if found, otherwise ``None``.
    """
    if not id_or_name:
        return None
    key = _safe(id_or_name)
    p = _copy_path(key)
    if os.path.exists(p):
        return p
    needle = str(id_or_name).strip().lower()
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


def _list_groups() -> List[Dict[str, Any]]:
    """
    List all groups stored in ``data/groups``.  Each returned dict is
    normalised to include ``id``, ``name``, ``multiplier`` and ``members``.
    The list is sorted alphabetically by group name.
    """
    items: List[Dict[str, Any]] = []
    try:
        for fn in os.listdir(GROUPS_ROOT):
            if not fn.endswith(".json"):
                continue
            doc = _read_json(os.path.join(GROUPS_ROOT, fn))
            if doc and isinstance(doc, dict):
                doc = dict(doc)  # shallow copy
                # ensure minimal fields
                doc["id"] = doc.get("id") or os.path.splitext(fn)[0]
                doc["name"] = doc.get("name") or doc["id"]
                doc["multiplier"] = float(doc.get("multiplier", 1))
                doc["members"] = doc.get("members") or []
                items.append(doc)
    except FileNotFoundError:
        pass
    items.sort(key=lambda d: (d.get("name") or "").lower())
    return items


def _find_group_path(id_or_name: str) -> Optional[str]:
    """
    Find a group JSON file by id or name (case insensitive).  Returns the
    absolute path or ``None`` if not found.
    """
    key = _safe(id_or_name)
    p = os.path.join(GROUPS_ROOT, f"{key}.json")
    if os.path.exists(p):
        return p
    needle = str(id_or_name).strip().lower()
    try:
        for fn in os.listdir(GROUPS_ROOT):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(GROUPS_ROOT, fn)
            doc = _read_json(path)
            nm = (doc.get("name") or "").strip().lower()
            if nm == needle:
                return path
    except FileNotFoundError:
        return None
    return None


def _delete(path: str) -> None:
    """
    Delete a local file and replicate the deletion to GitHub (if enabled).  If
    the file does not exist the function returns silently.  Errors during
    GitHub operations are suppressed to preserve compatibility with the
    original behaviour.
    """
    try:
        os.remove(path)
        # Mirror to GitHub
        try:
            rel_path = os.path.relpath(path, BASE_DIR).replace("\\", "/")
            _github_file_delete(rel_path)
        except Exception:
            pass
    except FileNotFoundError:
        pass
    except Exception:
        pass


###############################################################################
# Copy‑trading helpers
###############################################################################

def _set_copy_enabled(payload: Dict[str, Any], value: bool) -> Dict[str, Any]:
    """
    Enable or disable copy‑trading setups based on ids or names.  Accepts
    ``ids`` and/or ``names`` arrays as well as optional ``id`` or ``name``
    scalars.  Returns a summary of which setups were changed.
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
        doc["id"] = doc.get("id") or os.path.splitext(os.path.basename(p))[0]
        _save(p, doc)
        changed.append(doc["id"])
    return {"success": True, "changed": changed, "enabled": value}


def _unique_copy_id(name: str) -> str:
    """
    Generate a unique identifier for a copy‑trading setup based on the given
    name.  If a file with the generated name already exists a numeric suffix
    is appended until an unused filename is found.
    """
    base = _safe(name) or "setup"
    cid = base
    i = 1
    while os.path.exists(_copy_path(cid)):
        i += 1
        cid = f"{base}-{i}"
    return cid


def _extract_children(raw_children: Any) -> List[str]:
    """
    Normalise a list of children (strings or dicts) into a de‑duplicated list
    of client identifiers.  Accepts a mixture of strings and objects with
    common keys (``userid``, ``client_id``, ``id``, ``value``, ``account``).
    """
    out: List[str] = []
    if isinstance(raw_children, list):
        for ch in raw_children:
            if isinstance(ch, str):
                cid = ch.strip()
            elif isinstance(ch, dict):
                cid = _pick(
                    ch.get("userid"),
                    ch.get("client_id"),
                    ch.get("id"),
                    ch.get("value"),
                    ch.get("account"),
                )
            else:
                cid = ""
            if cid and cid not in out:
                out.append(str(cid))
    return out


def _build_multipliers(children: List[str], rawm: Any) -> Dict[str, float]:
    """
    Build a mapping of child identifiers to multiplier values.  Any non‑numeric
    or missing multipliers default to 1.0.
    """
    mm: Dict[str, float] = {}
    rawm = rawm or {}
    for c in children:
        try:
            mm[c] = float(rawm.get(c, 1))
        except Exception:
            mm[c] = 1.0
    return mm


###############################################################################
# Motilal login helpers
###############################################################################

def _has_required_for_login(c: Dict[str, Any]) -> bool:
    """
    Determine if a client document has the minimum fields required to attempt
    a Motilal login: ``password``, ``pan``, ``apikey`` and ``totpkey`` must all
    be non‑empty strings.
    """
    return all(
        (
            (c.get("password") or "").strip(),
            (c.get("pan") or "").strip(),
            (c.get("apikey") or "").strip(),
            (c.get("totpkey") or "").strip(),
        )
    )


def _dispatch_login(broker: str, path: str) -> None:
    """
    Background task to perform a Motilal login.  Reads the client JSON from
    ``path``, validates that required fields are present, imports the
    ``Broker_motilal`` module, calls its ``login`` function and updates the
    stored JSON with the session status and any returned token metadata.
    """
    try:
        client = _read_json(path)
        # Validate minimum fields
        if broker != "motilal" or not _has_required_for_login(client):
            print(
                f"[router] skip login (motilal/{client.get('userid')})"
                ": missing required fields"
            )
            return
        mod = importlib.import_module("Broker_motilal")
        login_fn = getattr(mod, "login", None)
        if not callable(login_fn):
            print("[router] Broker_motilal.login() not found")
            return
        result = login_fn(client)  # type: ignore[call-arg]
        # Determine login status
        ok = bool(result if not isinstance(result, dict) else result.get("ok", True))
        # Update token metadata if provided
        if isinstance(result, dict):
            if result.get("token_validity_raw") or result.get("token_validity_iso"):
                client["token_validity"] = result.get("token_validity_raw") or result.get(
                    "token_validity_iso"
                )
                client["token_validity_iso"] = result.get("token_validity_iso", "")
            if result.get("token_days_left") is not None:
                client["token_days_left"] = int(result["token_days_left"])
            if result.get("token_warning") is not None:
                client["token_warning"] = bool(result["token_warning"])
            client["last_token_check"] = datetime.utcnow().isoformat() + "Z"
            if result.get("message"):
                print(f"[router] login message: {result['message']}")
        client["session_active"] = ok
        _save(path, client)
    except ModuleNotFoundError:
        print("[router] Broker_motilal module not found")
    except Exception as e:
        print(f"[router] login error (motilal): {e}")


###############################################################################
# Health endpoints
###############################################################################

@app.get("/")
def root_health() -> Dict[str, str]:
    """Simple root health check to confirm the API is running."""
    return {"status": "ok"}


@app.get("/health")
def health() -> Dict[str, Any]:
    """
    Health endpoint that reports the readiness of the Motilal broker.  Always
    returns ``motilal: ready`` since only Motilal is supported.
    """
    return {"ok": True, "brokers": {"motilal": "ready"}}


###############################################################################
# Client endpoints
###############################################################################

@app.post("/clients/add")
def add_client(
    background_tasks: BackgroundTasks,
    payload: Dict[str, Any] = Body(...),
    user_id: str = Header(..., alias="X-User-Id"),
) -> Dict[str, Any]:
    """
    Create a new Motilal client for the authenticated user.

    The client details are persisted under ``data/users/<user>/clients/motilal``
    and mirrored to GitHub if enabled.  After saving, a background login
    attempt is triggered.

    Payload fields:

    * ``client_id`` or ``userid`` – the client identifier (required).
    * ``name`` or ``display_name`` – optional display name (defaults to id).
    * ``password`` – Motilal password.
    * ``pan`` – PAN number.
    * ``apikey`` – API key.
    * ``totpkey`` – TOTP secret.
    * ``capital`` – optional starting capital.
    * ``creds`` – optional nested dict containing the above keys.

    Returns a success indicator and echoes the client id and broker.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing X-User-Id header")
    broker = "motilal"
    client_id = _pick(payload.get("client_id"), payload.get("userid"))
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id / userid required")
    name = _pick(payload.get("name"), payload.get("display_name"), client_id)
    creds = payload.get("creds") or {}
    doc = {
        "broker": broker,
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
    path = _user_client_path(user_id, broker, client_id)
    _save(path, doc)
    # Trigger login in the background
    background_tasks.add_task(_dispatch_login, broker, path)
    return {
        "success": True,
        "broker": broker,
        "client_id": client_id,
        "message": "Client saved. Login triggered if credentials are valid.",
    }


@app.post("/clients/edit")
def edit_client(
    background_tasks: BackgroundTasks,
    payload: Dict[str, Any] = Body(...),
    user_id: str = Header(..., alias="X-User-Id"),
) -> Dict[str, Any]:
    """
    Edit an existing Motilal client for the authenticated user.  Fields left
    blank will preserve existing values.  Optional ``original_userid`` (or
    ``old_userid``) can be provided to rename or move a client.  After
    saving, a background login attempt is triggered.

    Returns a success indicator and a status message.
    """
    uid = (user_id or "").strip().lower()
    if not uid:
        raise HTTPException(status_code=400, detail="Missing X-User-Id header")
    broker = "motilal"
    old_client_id = _pick(payload.get("original_userid"), payload.get("old_userid"))
    client_id = _pick(payload.get("client_id"), payload.get("userid"), old_client_id)
    if not client_id:
        raise HTTPException(status_code=400, detail="client_id / userid is required for edit")
    name = _pick(payload.get("name"), payload.get("display_name"), client_id)
    old_path: Optional[str] = (
        _user_client_path(uid, broker, old_client_id) if old_client_id else None
    )
    new_path: str = _user_client_path(uid, broker, client_id)
    # Load existing data (prefer old if exists, otherwise new)
    existing: Dict[str, Any] = {}
    try:
        if old_path and os.path.exists(old_path):
            existing = _read_json(old_path)
        elif os.path.exists(new_path):
            existing = _read_json(new_path)
    except Exception:
        existing = {}
    creds = payload.get("creds") or {}
    doc = {
        "userid": client_id,
        "name": _pick(name, existing.get("name")),
        "password": _pick(
            payload.get("password"), creds.get("password"), existing.get("password")
        ),
        "pan": _pick(
            payload.get("pan"), creds.get("pan"), existing.get("pan")
        ),
        "apikey": _pick(
            payload.get("apikey"), creds.get("apikey"), existing.get("apikey")
        ),
        "totpkey": _pick(
            payload.get("totpkey"), creds.get("totpkey"), existing.get("totpkey")
        ),
        "capital": payload.get("capital", existing.get("capital")),
        "session_active": existing.get("session_active", False),
    }
    _save(new_path, doc)
    # If moved/renamed, remove the old file
    if old_path and os.path.abspath(old_path) != os.path.abspath(new_path):
        try:
            if os.path.exists(old_path):
                os.remove(old_path)
                try:
                    rel_path = os.path.relpath(old_path, BASE_DIR).replace("\\", "/")
                    _github_file_delete(rel_path)
                except Exception:
                    pass
        except Exception:
            pass
    # Trigger login
    background_tasks.add_task(_dispatch_login, broker, new_path)
    return {
        "success": True,
        "message": "Updated. Login started if fields complete.",
    }


@app.get("/clients")
def clients_rows(
    response: Response, user_id: str = Header(..., alias="X-User-Id")
) -> List[Dict[str, Any]]:
    """
    List all Motilal clients for the authenticated user.  When GitHub
    persistence is enabled the client list is fetched from the repository;
    otherwise it falls back to the local filesystem.  Caching headers are
    disabled to ensure fresh data in browsers and CDNs.
    """
    # Disable caching
    response.headers["Cache-Control"] = "no-store, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    uid = (user_id or "").strip().lower()
    if not uid:
        return []
    rows: List[Dict[str, Any]] = []
    # Prefer GitHub if enabled
    if _github_enabled():
        rel_dir = f"users/{_safe(uid)}/clients/motilal"
        items: List[Dict[str, Any]] = []
        try:
            items = _github_list_dir(rel_dir)
        except Exception:
            items = []
        for it in items:
            try:
                if (it.get("type") != "file"):
                    continue
                name = it.get("name") or ""
                if not name.endswith(".json"):
                    continue
                rel_path = f"{rel_dir}/{name}"
                d = _github_read_json(rel_path) or {}
                if not d:
                    continue
                rows.append(
                    {
                        "name": d.get("name", "") or d.get("display_name", "") or "",
                        "display_name": d.get("name", "") or d.get("display_name", "") or "",
                        "client_id": d.get("userid", "") or d.get("client_id", "") or "",
                        "capital": d.get("capital", "") or "",
                        "status": "logged_in" if d.get("session_active") else "logged_out",
                        "session_active": bool(d.get("session_active", False)),
                        "broker": d.get("broker", "motilal"),
                    }
                )
            except Exception:
                continue
        return rows
    # Fall back to local files
    folder = os.path.join(_user_clients_root(uid), "motilal")
    try:
        for fn in os.listdir(folder):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(folder, fn)
            try:
                d = _read_json(path)
                rows.append(
                    {
                        "name": d.get("name", "") or d.get("display_name", "") or "",
                        "display_name": d.get("name", "") or d.get("display_name", "") or "",
                        "client_id": d.get("userid", "") or d.get("client_id", "") or "",
                        "capital": d.get("capital", "") or "",
                        "status": "logged_in" if d.get("session_active") else "logged_out",
                        "session_active": bool(d.get("session_active", False)),
                        "broker": d.get("broker", "motilal"),
                    }
                )
            except Exception:
                pass
    except FileNotFoundError:
        pass
    return rows


@app.get("/get_clients")
def get_clients_legacy(
    response: Response, user_id: str = Header(..., alias="X-User-Id")
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Legacy endpoint returning clients wrapped in a ``clients`` key.  The
    structure matches the original single‑user implementation for backwards
    compatibility with older front‑ends.
    """
    rows = clients_rows(response=response, user_id=user_id)
    return {
        "clients": [
            {
                "name": r.get("name", ""),
                "client_id": r.get("client_id", ""),
                "capital": r.get("capital", ""),
                "session": "Logged in" if r.get("session_active") else "Logged out",
                "broker": r.get("broker", ""),
            }
            for r in (rows or [])
        ]
    }


@app.post("/clients/delete")
def delete_client(
    payload: Dict[str, Any] = Body(...),
    user_id: str = Header(..., alias="X-User-Id"),
) -> Dict[str, Any]:
    """
    Delete one or more Motilal clients for the authenticated user.  Accepts
    any of these shapes:

      - ``{ client_id: 'WOIE1286' }``
      - ``{ userid: 'WOIE1286' }``
      - ``{ items: [ { client_id:'WOIE1286' }, { userid:'123456' } ] }``
      - ``{ userids:['WOIE1286','WOIE1284'] }``

    Returns a summary with ``deleted`` and ``missing`` arrays.
    """
    if not user_id:
        raise HTTPException(status_code=400, detail="Missing X-User-Id header")
    deleted: List[Dict[str, str]] = []
    missing: List[Dict[str, str]] = []
    # unify into a list of items with client_id
    items: List[Dict[str, str]] = []
    if "items" in payload and isinstance(payload["items"], list):
        items = payload["items"]
    elif "userids" in payload and isinstance(payload["userids"], list):
        items = [{"client_id": u} for u in payload["userids"]]
    else:
        items = [payload]
    uid = (user_id or "").strip().lower()
    for it in items:
        client_id = _pick(it.get("client_id"), it.get("userid"))
        if not client_id:
            missing.append(
                {"client_id": client_id or "", "reason": "missing client_id"}
            )
            continue
        path = _user_client_path(uid, "motilal", client_id)
        try:
            if os.path.exists(path):
                os.remove(path)
                # Remove from GitHub as well
                try:
                    rel_path = os.path.relpath(path, BASE_DIR).replace("\\", "/")
                    _github_file_delete(rel_path)
                except Exception:
                    pass
                deleted.append({"client_id": client_id})
            else:
                missing.append(
                    {"client_id": client_id, "reason": "not found"}
                )
        except Exception as e:
            missing.append(
                {"client_id": client_id, "reason": str(e)}
            )
    return {"success": True, "deleted": deleted, "missing": missing}


###############################################################################
# Group endpoints
###############################################################################

@app.get("/groups")
def get_groups() -> Dict[str, List[Dict[str, Any]]]:
    """
    Return all saved groups.  Each group includes its ``id``, ``name``,
    ``multiplier`` and ``members`` array.
    """
    return {"groups": _list_groups()}


@app.get("/get_groups")
def get_groups_alias() -> Dict[str, List[Dict[str, Any]]]:
    """Alias for :func:`get_groups` to support legacy front‑ends."""
    return get_groups()


@app.post("/add_group")
def add_group(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Create a new group.  Payload must include ``name`` and at least one
    ``member``.  A group id can be provided explicitly; otherwise the name
    is used as the id.  The ``multiplier`` defaults to 1.0.

    Only members with broker ``motilal`` are accepted; any other broker
    entries are silently ignored.
    """
    name = _pick(payload.get("name"))
    if not name:
        raise HTTPException(status_code=400, detail="group 'name' is required")
    group_id = _pick(payload.get("id"), name)
    try:
        mult_raw = payload.get("multiplier", 1)
        multiplier = float(mult_raw) if str(mult_raw).strip() else 1.0
        if multiplier <= 0:
            raise ValueError("multiplier must be > 0")
    except Exception:
        raise HTTPException(status_code=400, detail="invalid 'multiplier'")
    raw_members = payload.get("members") or []
    members: List[Dict[str, str]] = []
    for m in raw_members:
        broker = (_pick((m or {}).get("broker")) or "").lower()
        userid = _pick((m or {}).get("userid"), (m or {}).get("client_id"))
        if not broker:
            broker = "motilal"
        if broker != "motilal" or not userid:
            # skip non‑motilal or malformed entries
            continue
        members.append({"broker": broker, "userid": userid})
    if not members:
        raise HTTPException(status_code=400, detail="at least one valid member is required")
    doc = {
        "id": _safe(group_id),
        "name": name,
        "multiplier": multiplier,
        "members": members,
    }
    path = _group_path(doc["id"])
    _save(path, doc)
    return {"success": True, "group": doc}


@app.post("/edit_group")
def edit_group(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Update an existing group.  Accepts ``id`` or ``name`` to identify the
    group and any of ``name``, ``multiplier`` or ``members`` to update.  The
    group id/filename remains stable.  If ``members`` is provided only
    Motilal members are kept; all others are ignored.
    """
    id_or_name = _pick(payload.get("id"), payload.get("name"))
    if not id_or_name:
        raise HTTPException(status_code=400, detail="group 'id' or 'name' is required")
    path = _find_group_path(id_or_name)
    if not path:
        raise HTTPException(status_code=404, detail="group not found")
    doc = _read_json(path) or {}
    # Update name
    if payload.get("name"):
        doc["name"] = str(payload["name"]).strip()
    # Update multiplier
    if "multiplier" in payload:
        try:
            m = float(payload.get("multiplier", 1))
            if m <= 0:
                raise ValueError
        except Exception:
            raise HTTPException(status_code=400, detail="invalid 'multiplier'")
        doc["multiplier"] = m
    # Update members
    if "members" in payload:
        raw = payload.get("members") or []
        members: List[Dict[str, str]] = []
        for m in raw:
            b = (_pick((m or {}).get("broker")) or "").lower()
            u = _pick((m or {}).get("userid"), (m or {}).get("client_id"))
            if not b:
                b = "motilal"
            if b == "motilal" and u:
                members.append({"broker": b, "userid": u})
        if not members:
            raise HTTPException(status_code=400, detail="at least one valid member is required")
        doc["members"] = members
    # Ensure id remains stable
    doc["id"] = doc.get("id") or os.path.splitext(os.path.basename(path))[0]
    _save(path, doc)
    return {"success": True, "group": doc}


@app.post("/delete_group")
def delete_group(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Delete one or more groups by id or name.  Accepts ``ids`` and/or
    ``names`` arrays as well as optional ``id`` or ``name`` scalars.  Returns
    a list of deleted group ids.
    """
    ids = payload.get("ids") or []
    names = payload.get("names") or []
    targets = [str(x) for x in (ids + names)]
    if not targets:
        raise HTTPException(status_code=400, detail="provide 'ids' or 'names'")
    deleted: List[str] = []
    for t in targets:
        p = _find_group_path(t)
        if p and os.path.exists(p):
            try:
                _delete(p)
                deleted.append(os.path.splitext(os.path.basename(p))[0])
            except Exception:
                pass
    return {"success": True, "deleted": deleted}


###############################################################################
# Copy‑trading endpoints
###############################################################################

@app.get("/list_copytrading_setups")
def list_copytrading_setups() -> Dict[str, List[Dict[str, Any]]]:
    """
    Return all saved copy‑trading setups.  Each setup includes at least an
    ``id`` and ``name``.  The list is sorted alphabetically.
    """
    items: List[Dict[str, Any]] = []
    try:
        for fn in os.listdir(COPY_ROOT):
            if not fn.endswith(".json"):
                continue
            path = os.path.join(COPY_ROOT, fn)
            doc = _read_json(path)
            if not isinstance(doc, dict):
                continue
            # ensure minimal fields
            doc = dict(doc)
            doc["id"] = doc.get("id") or os.path.splitext(fn)[0]
            doc["name"] = doc.get("name") or doc["id"]
            items.append(doc)
    except FileNotFoundError:
        pass
    items.sort(key=lambda d: (d.get("name") or "").lower())
    return {"setups": items}


@app.post("/add_copy_setup")
def add_copy_setup(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Alias for :func:`save_copytrading_setup` to create a new setup."""
    return save_copytrading_setup(payload)


@app.post("/edit_copy_setup")
def edit_copy_setup(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Alias for :func:`save_copytrading_setup` to update an existing setup."""
    return save_copytrading_setup(payload)


@app.post("/enable_copy")
def enable_copy(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Enable one or more copy‑trading setups by id or name."""
    return _set_copy_enabled(payload, True)


@app.post("/disable_copy")
def disable_copy(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Disable one or more copy‑trading setups by id or name."""
    return _set_copy_enabled(payload, False)


@app.post("/save_copytrading_setup")
def save_copytrading_setup(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Create or update a copy‑trading setup.  Accepts either UI or generic keys:

    ``id`` (optional), ``name``/``setup_name``, ``master``/``master_account``,
    ``children``/``child_accounts`` (list of client ids or dicts),
    ``multipliers`` (mapping of child id to float) and ``enabled``.

    If ``id`` is provided and a matching file exists the setup is updated.
    Otherwise a new setup id is generated based on the name.  The master
    account is removed from the children list if present.
    """
    name = _pick(payload.get("name"), payload.get("setup_name"))
    master = _pick(payload.get("master"), payload.get("master_account"))
    children = _extract_children(
        payload.get("children") or payload.get("child_accounts") or []
    )
    # remove master if present in children
    children = [c for c in children if c != master]
    if not name or not master or not children:
        raise HTTPException(status_code=400, detail="name, master, and children are required")
    multipliers = _build_multipliers(children, payload.get("multipliers"))
    enabled = bool(payload.get("enabled", False))
    mode = "created"
    doc: Dict[str, Any] = {}
    # resolve update path by id or (fallback) by name
    setup_id = _pick(payload.get("id"))
    path: Optional[str] = None
    if setup_id:
        path = _find_copy_path(setup_id)
    if not path:
        # try by name
        path = _find_copy_path(name)
    if path and os.path.exists(path):
        # UPDATE
        mode = "updated"
        doc = _read_json(path) or {}
        doc["name"] = name
        doc["master"] = str(master)
        doc["children"] = children
        doc["multipliers"] = multipliers
        if "enabled" in payload:
            doc["enabled"] = enabled
        doc["id"] = doc.get("id") or os.path.splitext(os.path.basename(path))[0]
    else:
        # CREATE
        setup_id = setup_id or _unique_copy_id(name)
        doc = {
            "id": setup_id,
            "name": name,
            "master": str(master),
            "children": children,
            "multipliers": multipliers,
            "enabled": enabled,
        }
        path = _copy_path(setup_id)
    _save(path, doc)
    return {"success": True, "mode": mode, "setup": doc}


@app.post("/delete_copy_setup")
def delete_copy_setup(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Delete copy‑trading setups by ids and/or names.  Accepts ``ids`` and
    ``names`` arrays as well as optional ``id`` or ``name`` scalars.  Returns
    a list of deleted setup ids.
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
    deleted: List[str] = []
    for t in targets:
        p = _find_copy_path(t)
        if p and os.path.exists(p):
            try:
                os.remove(p)
                try:
                    rel_path = os.path.relpath(p, BASE_DIR).replace("\\", "/")
                    _github_file_delete(rel_path)
                except Exception:
                    pass
                deleted.append(os.path.splitext(os.path.basename(p))[0])
            except Exception:
                pass
    return {"success": True, "deleted": deleted}


@app.post("/delete_copytrading_setup")
def delete_copytrading_setup(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Compatibility alias for :func:`delete_copy_setup`."""
    return delete_copy_setup(payload)


###############################################################################
# GitHub directory listing and file read helpers (used in clients listing)
###############################################################################

def _github_read_json(rel_path: str) -> Dict[str, Any]:
    """
    Read and decode a JSON file from GitHub under the ``data/`` prefix.  If
    GitHub persistence is disabled or any error occurs an empty dict is
    returned.
    """
    if not _github_enabled():
        return {}
    try:
        path_in_repo = ("data/" + rel_path.lstrip("/")).replace("\\", "/")
        url = _gh_contents_url(path_in_repo)
        r = requests.get(url, headers=_gh_headers(), params={"ref": GITHUB_BRANCH}, timeout=30)
        if r.status_code != 200:
            return {}
        j = r.json() or {}
        b64 = j.get("content") or ""
        if not b64:
            return {}
        raw = base64.b64decode(b64.encode("utf-8")).decode("utf-8", errors="ignore")
        return json.loads(raw) if raw.strip() else {}
    except Exception as e:
        print(f"[GITHUB] read_json failed for {rel_path}: {e}")
        return {}


def _github_list_dir(rel_dir: str) -> List[Dict[str, Any]]:
    """
    List a directory in the GitHub repository under the ``data/`` prefix.
    Returns an empty list on error or if GitHub persistence is disabled.
    """
    if not _github_enabled():
        return []


###############################################################################
# Motilal order and portfolio endpoints
###############################################################################

def _safe_int(val: Any, default: int = 0) -> int:
    """
    Best‑effort conversion of arbitrary input into an integer.  Empty strings
    evaluate to the provided default.  If the input cannot be converted,
    ``default`` is returned.

    Parameters
    ----------
    val: Any
        The value to convert.
    default: int, optional
        Fallback value when conversion fails.  Defaults to 0.

    Returns
    -------
    int
        Parsed integer or ``default``.
    """
    try:
        if val is None:
            return default
        s = str(val).strip()
        if s == "":
            return default
        return int(float(s))
    except Exception:
        return default


def _index_clients(user_id: str | None = None) -> Dict[str, Dict[str, Any]]:
    """
    Build an index of Motilal clients keyed by userid.  If ``user_id`` is
    provided only that user's clients are indexed; otherwise all users are
    scanned.  Each entry contains the broker (always ``motilal`` in this
    implementation), the loaded JSON document and a display name.

    Parameters
    ----------
    user_id: str | None
        Optional user identifier to restrict the search to a single user's
        clients.  When ``None`` all user directories are scanned.

    Returns
    -------
    Dict[str, Dict[str, Any]]
        Mapping of userid → dict with keys ``broker``, ``json`` and ``name``.
    """
    idx: Dict[str, Dict[str, Any]] = {}
    users: List[str] = []
    # Determine which user directories to scan
    if user_id:
        users = [_safe(user_id)] if _safe(user_id) else []
    else:
        try:
            users = [d for d in os.listdir(USERS_ROOT) if os.path.isdir(os.path.join(USERS_ROOT, d))]
        except Exception:
            users = []
    for uid in users:
        folder = os.path.join(USERS_ROOT, uid, "clients", "motilal")
        try:
            for fn in os.listdir(folder):
                if not fn.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(folder, fn), "r", encoding="utf-8") as f:
                        cj = json.load(f)
                except Exception:
                    continue
                # derive userid and name
                cid = str(cj.get("userid") or cj.get("client_id") or "").strip()
                if not cid:
                    continue
                idx[cid] = {
                    "broker": "motilal",
                    "json": cj,
                    "name": cj.get("name") or cj.get("display_name") or cid,
                }
        except FileNotFoundError:
            continue
    return idx


def _pick_qty_for_client(ci: Dict[str, Any], per_client_qty: Dict[str, Any], default_qty: int) -> int:
    """
    Resolve a per‑client quantity from a user‑provided map.  Several keys are
    tried in turn: ``userid``/``client_id``, the client's display name and
    the display name up to the first colon (to support labels like
    ``"Edison : 1100922501"``).  If none of the candidate keys match in
    ``per_client_qty`` the ``default_qty`` is returned.

    Parameters
    ----------
    ci: Dict[str, Any]
        Client descriptor containing ``userid`` and ``name`` fields.
    per_client_qty: Dict[str, Any]
        Mapping of keys to quantities.
    default_qty: int
        Fallback quantity if no matches found.

    Returns
    -------
    int
        The resolved quantity for the client.
    """
    if not isinstance(per_client_qty, dict):
        return default_qty
    keys: List[str] = []
    keys.append(str(ci.get("userid") or ci.get("client_id") or "").strip())
    nm = (ci.get("name") or ci.get("display_name") or "").strip()
    if nm:
        keys.append(nm)
        keys.append(nm.split(":")[0].strip())
    for k in keys:
        if k and k in per_client_qty:
            q = _safe_int(per_client_qty.get(k), default=None)
            if q is not None:
                return q
    return default_qty


@app.post("/place_orders")
def route_place_orders(
    payload: Dict[str, Any] = Body(...),
    user_id: str = Header(None, alias="X-User-Id"),
) -> Dict[str, Any]:
    """
    Place one or more Motilal orders.  This endpoint accepts the same
    payload shape as the single‑user implementation but operates only on
    Motilal clients.  When ``groupacc`` is true the ``groups`` field should
    contain the identifiers or names of groups to send the orders to; the
    group documents are loaded from ``data/groups``.  If ``groupacc`` is
    false the ``clients`` array is interpreted as a list of individual
    client IDs.  Quantities can be provided per client or per group via
    ``perClientQty`` and ``perGroupQty`` respectively.  When not provided
    the default quantity ``quantityinlot`` is used.

    The final list of order dictionaries is dispatched to the broker module
    ``Broker_motilal`` via its ``place_orders`` function if available.  The
    returned result from the broker call is included in the response.
    """
    data = payload or {}

    # Robust symbol parsing ("NSE|PNB EQ|110666|17000")
    raw_symbol = (data.get("symbol") or "").strip()
    explicit_tok = data.get("symboltoken") or data.get("token")
    parts = [p.strip() for p in raw_symbol.split("|") if p is not None]
    exchange_from_symbol = parts[0] if len(parts) > 0 else ""
    stock_symbol = parts[1] if len(parts) > 1 else ""
    symboltoken = parts[3] if len(parts) > 3 else ""
    if not symboltoken and explicit_tok:
        symboltoken = str(explicit_tok)
    exchange_val = (data.get("exchange") or exchange_from_symbol or "NSE").upper()

    # Common UI fields
    groupacc = bool(data.get("groupacc", False))
    groups_sel: List[str] = data.get("groups", []) or []
    clients_sel: List[str] = data.get("clients", []) or []
    diffQty = bool(data.get("diffQty", False))
    multiplier_flag = bool(data.get("multiplier", False))
    qtySelection = data.get("qtySelection", "manual")
    quantityinlot = int(data.get("quantityinlot", 0) or 0)
    perClientQty = data.get("perClientQty", {}) or {}
    perGroupQty = data.get("perGroupQty", {}) or {}
    action = (data.get("action") or "").upper()
    ordertype = (data.get("ordertype") or "").upper()
    producttype = data.get("producttype") or ""
    orderduration = data.get("orderduration") or "DAY"
    price = float(data.get("price", 0) or 0)
    triggerprice = float(data.get("triggerprice", 0) or 0)
    disclosedqty = int(data.get("disclosedquantity", 0) or 0)
    amoorder = data.get("amoorder", "N")
    correlation_id = data.get("correlationId") or data.get("correlation_id") or ""

    if ordertype == "LIMIT" and price <= 0:
        raise HTTPException(status_code=400, detail="Price must be > 0 for LIMIT orders.")
    if "SL" in ordertype and triggerprice <= 0:
        raise HTTPException(status_code=400, detail="Trigger price is required for SL/SL-M orders.")

    # Build an index of clients for the current user (or all if header missing)
    client_index = _index_clients(user_id)

    # Helper to build one order dictionary
    def _build_order(client_id: str, qty: int, tag: Optional[str]) -> Dict[str, Any]:
        ci = client_index.get(str(client_id))
        if not ci:
            # Include a marker to skip this order
            return {"_skip": True, "reason": "client_not_found", "client_id": client_id}
        return {
            "client_id": str(client_id),
            "name": ci["name"],
            "broker": ci["broker"],  # always motilal
            "action": action,
            "ordertype": ordertype,
            "producttype": producttype,
            "orderduration": orderduration,
            "exchange": exchange_val,
            "price": price,
            "triggerprice": triggerprice,
            "disclosedquantity": disclosedqty,
            "amoorder": amoorder,
            "qty": int(qty),
            "tag": tag or "",
            "correlation_id": correlation_id,
            "symbol": raw_symbol,
            "symboltoken": str(symboltoken or ""),
            "stock_symbol": stock_symbol,
        }

    # Expand to per‑client orders
    per_client_orders: List[Dict[str, Any]] = []
    if groupacc:
        # Helper to extract member ids from a group document
        def _member_ids(doc: Dict[str, Any]) -> List[str]:
            out: List[str] = []
            raw = doc.get("members") or []
            for m in raw:
                if isinstance(m, dict):
                    uid = (m.get("userid") or m.get("client_id") or m.get("id") or "").strip()
                else:
                    uid = str(m).strip()
                if uid and uid not in out:
                    out.append(uid)
            return out
        for gsel in groups_sel:
            # Attempt to locate the group JSON file by id or name
            gp = _find_group_path(gsel)
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
            gkey = gdoc.get("id") or gname
            members = _member_ids(gdoc)
            group_multiplier = int(gdoc.get("multiplier", 1) or 1)
            for client_id in members:
                if qtySelection == "auto":
                    # auto sizing not yet implemented for multi‑user; fall back to quantityinlot
                    q = quantityinlot
                elif diffQty:
                    q = int((perGroupQty.get(gkey) or perGroupQty.get(gname) or 0) or 0)
                elif multiplier_flag:
                    q = quantityinlot * group_multiplier
                else:
                    q = quantityinlot
                per_client_orders.append(_build_order(str(client_id), q, gname))
    else:
        for client_id in clients_sel:
            if qtySelection == "auto":
                q = quantityinlot  # auto sizing not implemented; fallback
            elif diffQty:
                q = int(perClientQty.get(str(client_id), 0) or 0)
            else:
                q = quantityinlot
            per_client_orders.append(_build_order(str(client_id), q, None))

    # Bucket by broker (only motilal in this version)
    by_broker: Dict[str, List[Dict[str, Any]]] = {"motilal": []}
    skipped: List[Dict[str, Any]] = []
    for od in per_client_orders:
        if od.get("_skip"):
            skipped.append(od)
            continue
        brk = od.get("broker")
        if brk == "motilal":
            by_broker.setdefault("motilal", []).append(od)

    # Print dispatch summary
    try:
        if by_broker.get("motilal"):
            logging.debug(f"[router] MOTILAL orders ({len(by_broker['motilal'])}) ->\n" + json.dumps(by_broker["motilal"], indent=2))
    except Exception:
        pass

    results: Dict[str, Any] = {"skipped": skipped}
    orders_list = by_broker.get("motilal", [])
    if orders_list:
        try:
            mod = importlib.import_module("Broker_motilal")
            try:
                mod = importlib.reload(mod)
            except Exception:
                pass
            fn = getattr(mod, "place_orders", None)
            if callable(fn):
                res = fn(orders_list)
            else:
                # fall back to single order if place_orders not provided
                single_fn = getattr(mod, "place_order", None)
                if callable(single_fn):
                    res = [single_fn(od) for od in orders_list]
                else:
                    res = {"status": "error", "message": "place_orders not implemented"}
        except Exception as e:
            res = {"status": "error", "message": str(e)}
        results["motilal"] = res
    return {"status": "completed", "result": results}


@app.post("/place_order")
def route_place_order_compat(
    payload: Dict[str, Any] = Body(...),
    user_id: str = Header(None, alias="X-User-Id"),
) -> Dict[str, Any]:
    """
    Compatibility layer for front‑ends posting to ``/place_order``.  Simply
    forwards the payload to :func:`route_place_orders`.  The optional
    ``X‑User‑Id`` header is passed through to restrict which clients may
    receive orders.
    """
    return route_place_orders(payload, user_id)


@app.get("/get_orders")
def route_get_orders() -> Dict[str, List[Dict[str, Any]]]:
    """
    Fetch the current order book for all logged in Motilal clients.  This
    implementation delegates to the ``Broker_motilal.get_orders`` function if
    available.  The return structure mirrors the single‑user implementation
    with buckets labelled ``pending``, ``traded``, ``rejected``, ``cancelled``
    and ``others``.
    """
    buckets = OrderedDict({k: [] for k in ["pending", "traded", "rejected", "cancelled", "others"]})
    try:
        mod = importlib.import_module("Broker_motilal")
        fn = getattr(mod, "get_orders", None)
        if callable(fn):
            res = fn()
            if isinstance(res, dict):
                for k in buckets.keys():
                    buckets[k].extend(res.get(k, []) or [])
    except Exception as e:
        logging.error(f"[router] get_orders error: {e}")
    return buckets


@app.get("/get_positions")
def route_get_positions() -> Dict[str, List[Dict[str, Any]]]:
    """
    Retrieve open and closed positions across all Motilal clients.  This
    function calls ``Broker_motilal.get_positions`` if present and merges
    its ``open`` and ``closed`` arrays into a single result.  Any
    exceptions during broker calls are logged and an empty structure is
    returned.
    """
    buckets = {"open": [], "closed": []}
    try:
        mod = importlib.import_module("Broker_motilal")
        fn = getattr(mod, "get_positions", None)
        if callable(fn):
            res = fn()
            if isinstance(res, dict):
                buckets["open"].extend(res.get("open", []) or [])
                buckets["closed"].extend(res.get("closed", []) or [])
    except Exception as e:
        logging.error(f"[router] get_positions error: {e}")
    return buckets


@app.post("/cancel_order")
def route_cancel_order(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Cancel one or more pending Motilal orders.  The payload must contain an
    ``orders`` array where each element has at minimum ``name`` (client
    display name) and ``order_id`` fields.  Orders with unknown client
    names are ignored.  The function calls the broker's ``cancel_orders``
    or ``cancel_order`` helper and aggregates the resulting messages.
    """
    orders = payload.get("orders", [])
    if not isinstance(orders, list) or not orders:
        raise HTTPException(status_code=400, detail="No orders received for cancellation.")
    messages: List[str] = []
    unknown: List[str] = []

    # Build list of orders to cancel per broker (only motilal)
    to_cancel: List[Dict[str, Any]] = []
    for od in orders:
        name = (od or {}).get("name", "").strip()
        if not name:
            unknown.append(str(od))
            continue
        to_cancel.append(od)

    if to_cancel:
        try:
            mod = importlib.import_module("Broker_motilal")
            # Prefer batch API
            cancel_many = getattr(mod, "cancel_orders", None)
            if callable(cancel_many):
                res = cancel_many(to_cancel)
                if isinstance(res, list):
                    messages.extend([str(x) for x in res])
                elif isinstance(res, dict) and isinstance(res.get("message"), list):
                    messages.extend([str(x) for x in res["message"]])
                else:
                    messages.append(str(res))
            else:
                # fallback: call cancel_order on each
                cancel_one = getattr(mod, "cancel_order", None)
                if callable(cancel_one):
                    for od in to_cancel:
                        try:
                            r = cancel_one(od)
                            if isinstance(r, dict) and r.get("message"):
                                messages.append(str(r["message"]))
                            else:
                                messages.append(str(r))
                        except Exception as e:
                            messages.append(f"Error cancelling {od.get('order_id')}: {str(e)}")
                else:
                    messages.append("cancel_orders not implemented in broker")
        except Exception as e:
            messages.append(f"Broker error: {str(e)}")
    if unknown:
        messages.append("Unknown client names for orders: " + ", ".join(sorted(set(unknown))))
    return {"message": messages}


@app.get("/get_holdings")
def route_get_holdings() -> Dict[str, Any]:
    """
    Fetch DP holdings and account summary for all Motilal clients.  The broker
    module's ``get_holdings`` function is called and its return value
    (expected to be a dict with ``holdings`` and ``summary`` keys) is
    flattened.  The per‑client summary is cached for the /get_summary
    endpoint.  Any errors during broker calls are logged.
    """
    global summary_data_global
    buckets = {"holdings": [], "summary": []}
    try:
        mod = importlib.import_module("Broker_motilal")
        fn = getattr(mod, "get_holdings", None)
        if callable(fn):
            res = fn()
            if isinstance(res, dict):
                buckets["holdings"].extend(res.get("holdings", []) or [])
                buckets["summary"].extend(res.get("summary", []) or [])
    except Exception as e:
        logging.error(f"[router] get_holdings error: {e}")
    # build summary_data_global keyed by name
    summary_data_global = {}
    for i, s in enumerate(buckets["summary"]):
        if isinstance(s, dict):
            key = s.get("name") or f"client_{i}"
            summary_data_global[key] = s
    return buckets


@app.get("/get_summary")
def route_get_summary() -> Dict[str, List[Dict[str, Any]]]:
    """
    Return the cached account summary computed by :func:`route_get_holdings`.
    The summary is wrapped in a ``summary`` key for backwards compatibility.
    """
    return {"summary": list(summary_data_global.values())}


@app.post("/close_positions")
def route_close_positions(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Close one or more open positions for Motilal clients.  The payload must
    contain a ``positions`` array with objects that include at least a
    ``name`` (client display name) and ``symbol``.  The function delegates
    to ``Broker_motilal.close_positions`` if available, passing the list of
    position descriptors verbatim.  Any returned messages are aggregated
    into a single response.
    """
    items = payload.get("positions")
    if not isinstance(items, list):
        raise HTTPException(status_code=400, detail="'positions' must be a list")
    messages: List[str] = []
    try:
        mod = importlib.import_module("Broker_motilal")
        fn = getattr(mod, "close_positions", None)
        if callable(fn):
            res = fn(items)
            if isinstance(res, list):
                messages.extend([str(x) for x in res])
            elif isinstance(res, dict):
                msgs = res.get("message") or res.get("messages") or []
                if isinstance(msgs, list):
                    messages.extend([str(x) for x in msgs])
                else:
                    messages.append(str(res))
        else:
            messages.append("close_positions not implemented in broker")
    except Exception as e:
        messages.append(f"Broker error: {str(e)}")
    return {"message": messages}


@app.post("/convert_position")
def route_convert_position(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Convert the product type of one or more positions for Motilal clients.
    The payload should include a ``positions`` array with each element
    containing ``name``, ``symbol``, ``quantity``, ``exchange``,
    ``oldproduct`` and ``newproduct``.  The implementation tries to call
    ``Broker_motilal.convert_positions`` or ``convert_position`` if
    available.  Any returned messages are collected.
    """
    data = payload or {}
    items = data.get("positions", [])
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="No positions received for conversion.")
    messages: List[str] = []
    try:
        mod = importlib.import_module("Broker_motilal")
        # Prefer batch API first
        fn_many = getattr(mod, "convert_positions", None)
        if callable(fn_many):
            res = fn_many(items)
            if isinstance(res, list):
                messages.extend([str(x) for x in res])
            elif isinstance(res, dict):
                msgs = res.get("message") or res.get("messages") or []
                if isinstance(msgs, list):
                    messages.extend([str(x) for x in msgs])
                else:
                    messages.append(str(res))
        else:
            # Fallback to single call
            fn_one = getattr(mod, "convert_position", None)
            if callable(fn_one):
                for itm in items:
                    try:
                        r = fn_one(itm)
                        if isinstance(r, dict) and r.get("message"):
                            messages.append(str(r["message"]))
                        else:
                            messages.append(str(r))
                    except Exception as e:
                        messages.append(f"Error converting {itm.get('symbol')}: {str(e)}")
            else:
                messages.append("convert_position(s) not implemented in broker")
    except Exception as e:
        messages.append(f"Broker error: {str(e)}")
    return {"message": messages}
    try:
        dir_in_repo = ("data/" + rel_dir.strip("/")).replace("\\", "/")
        url = _gh_contents_url(dir_in_repo)
        r = requests.get(url, headers=_gh_headers(), params={"ref": GITHUB_BRANCH}, timeout=30)
        if r.status_code != 200:
            return []
        j = r.json()
        return j if isinstance(j, list) else []
    except Exception as e:
        print(f"[GITHUB] list_dir failed for {rel_dir}: {e}")
        return []

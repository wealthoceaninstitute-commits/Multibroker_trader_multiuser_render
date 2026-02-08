"""
Functions for persisting and retrieving JSON data from GitHub.

These helpers wrap the GitHub Contents API so that user profiles,
clients and other state can be stored in a repository.  When the
environment variables required to talk to GitHub are not set the
``gh_enabled`` function will return ``False`` and calling any of
the put/get functions will raise an HTTPException.
"""

from __future__ import annotations

import base64
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import requests
from fastapi import HTTPException


# Read configuration from environment.  Use sensible defaults when
# unset so that unit tests can run without hitting external services.
GITHUB_OWNER: str = os.getenv("GITHUB_OWNER", "")
GITHUB_REPO: str = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH: str = os.getenv("GITHUB_BRANCH", "main")
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")


def gh_enabled() -> bool:
    """Return True if GitHub storage is configured."""
    return bool(GITHUB_OWNER and GITHUB_REPO and GITHUB_TOKEN)


def gh_headers() -> Dict[str, str]:
    """Return HTTP headers for GitHub API requests."""
    h: Dict[str, str] = {
        "Accept": "application/vnd.github+json",
    }
    if GITHUB_TOKEN:
        h["Authorization"] = f"token {GITHUB_TOKEN}"
    return h


def gh_url(path: str) -> str:
    """Return the GitHub API URL for a given repository relative path."""
    # Normalise path: remove leading slash and convert backslashes to forward slashes
    path = path.lstrip("/").replace("\\", "/")
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"


def b64encode_str(s: str) -> str:
    return base64.b64encode(s.encode("utf-8")).decode("utf-8")


def b64decode_to_str(s: str) -> str:
    return base64.b64decode(s.encode("utf-8")).decode("utf-8")


def gh_get_json(path: str) -> Tuple[Optional[Any], Optional[str]]:
    """Retrieve a JSON file from GitHub returning (object, sha).

    Returns ``(None, None)`` if the file does not exist.  If the
    content cannot be parsed as JSON a dict with a ``"_raw"`` key
    containing the raw string is returned.
    """
    if not gh_enabled():
        return None, None
    r = requests.get(gh_url(path), headers=gh_headers(), params={"ref": GITHUB_BRANCH})
    if r.status_code == 404:
        return None, None
    r.raise_for_status()
    data = r.json()
    if isinstance(data, dict) and data.get("type") == "file":
        content = (data.get("content") or "").replace("\n", "")
        sha: Optional[str] = data.get("sha")
        text = b64decode_to_str(content) if content else ""
        if not text:
            return {}, sha
        try:
            return json.loads(text), sha
        except Exception:
            return {"_raw": text}, sha
    return data, data.get("sha")  # type: ignore[return-value]


def gh_put_json(path: str, obj: Any, message: str) -> None:
    """Create or update a JSON file at ``path`` with commit message ``message``."""
    if not gh_enabled():
        raise HTTPException(500, "GitHub storage not configured (set GITHUB_OWNER/GITHUB_REPO/GITHUB_TOKEN)")
    # Determine current sha for update
    _, sha = gh_get_json(path)
    payload: Dict[str, Any] = {
        "message": message,
        "content": b64encode_str(json.dumps(obj, indent=2, ensure_ascii=False)),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(gh_url(path), headers=gh_headers(), json=payload)
    r.raise_for_status()


def gh_list_dir(path: str) -> List[Dict[str, Any]]:
    """List the contents of a directory via the GitHub Contents API."""
    if not gh_enabled():
        raise HTTPException(500, "GitHub storage not configured (set GITHUB_OWNER/GITHUB_REPO/GITHUB_TOKEN)")
    r = requests.get(gh_url(path), headers=gh_headers(), params={"ref": GITHUB_BRANCH})
    if r.status_code == 404:
        return []
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []
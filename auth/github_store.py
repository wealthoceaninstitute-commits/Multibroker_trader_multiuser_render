import base64
import json
import os
import time
from typing import Any, Dict, Optional, Tuple

import requests


def _env(name: str, default: Optional[str] = None) -> str:
    v = os.getenv(name, default)
    return v if v is not None else ""


class GitHubStore:
    """Tiny GitHub Contents API wrapper for JSON files.

    Uses:
      - GITHUB_TOKEN (PAT)
      - GITHUB_REPO (owner/repo) e.g. wealthoceaninstitute-commits/Multisuer_clients
      - GITHUB_BRANCH (default: main)
    Optional:
      - GITHUB_API_BASE (default: https://api.github.com)
      - GITHUB_DATA_REPO (if you store auth data in a different repo than code)
    """

    def __init__(self):
        self.token = _env("GITHUB_TOKEN")
        self.repo = _env("GITHUB_DATA_REPO") or _env("GITHUB_REPO")
        self.branch = _env("GITHUB_BRANCH", "main")
        self.api_base = _env("GITHUB_API_BASE", "https://api.github.com").rstrip("/")

        if not self.token or not self.repo:
            raise RuntimeError("Missing GITHUB_TOKEN or GITHUB_REPO (or GITHUB_DATA_REPO).")

        self._headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "motilal-multiuser-auth",
        }

    def _contents_url(self, path: str) -> str:
        path = path.lstrip("/")
        return f"{self.api_base}/repos/{self.repo}/contents/{path}"

    def get_json(self, path: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Returns (data, sha). If file not found, returns (None, None)."""
        url = self._contents_url(path)
        r = requests.get(url, headers=self._headers, params={"ref": self.branch}, timeout=20)
        if r.status_code == 404:
            return None, None
        r.raise_for_status()
        payload = r.json()
        if payload.get("type") != "file":
            raise RuntimeError(f"Path is not a file: {path}")
        content_b64 = payload.get("content", "")
        sha = payload.get("sha")
        raw = base64.b64decode(content_b64).decode("utf-8")
        return json.loads(raw or "{}"), sha

    def put_json(self, path: str, data: Dict[str, Any], message: str, sha: Optional[str] = None) -> Dict[str, Any]:
        """Create or update JSON file. Handles one retry on SHA conflict."""
        url = self._contents_url(path)
        body = {
            "message": message,
            "content": base64.b64encode(json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")).decode("utf-8"),
            "branch": self.branch,
        }
        if sha:
            body["sha"] = sha

        r = requests.put(url, headers=self._headers, json=body, timeout=25)

        # If SHA conflict, refetch and retry once (helps when two writes happen close together)
        if r.status_code == 409:
            time.sleep(0.6)
            _, new_sha = self.get_json(path)
            if new_sha and sha != new_sha:
                body["sha"] = new_sha
                r = requests.put(url, headers=self._headers, json=body, timeout=25)

        r.raise_for_status()
        return r.json()

    def ensure_folder_placeholder(self, folder_path: str):
        """GitHub doesn't store empty folders. We create a .keep file so the folder is visible."""
        folder_path = folder_path.strip("/")

        keep_path = f"{folder_path}/.keep"
        existing, _ = self.get_json(keep_path)
        if existing is not None:
            return

        self.put_json(
            keep_path,
            {"keep": True},
            message=f"init {folder_path}",
            sha=None,
        )

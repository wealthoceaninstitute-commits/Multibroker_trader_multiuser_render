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

    Supports both env styles:
      Style A (single):
        - GITHUB_REPO = owner/repo
      Style B (split, like your Render UI):
        - GITHUB_OWNER = owner
        - GITHUB_REPO = repo

    Required:
      - GITHUB_TOKEN (PAT)
      - GITHUB_REPO (either owner/repo OR repo name with GITHUB_OWNER)
    Optional:
      - GITHUB_DATA_REPO (owner/repo) to store auth data in a different repo
      - GITHUB_BRANCH (default: main)
      - GITHUB_API_BASE (default: https://api.github.com)
    """

    def __init__(self):
        self.token = _env("GITHUB_TOKEN")
        self.branch = _env("GITHUB_BRANCH", "main")
        self.api_base = _env("GITHUB_API_BASE", "https://api.github.com").rstrip("/")

        # Prefer explicit data repo, else fall back to code repo variables
        repo_full = _env("GITHUB_DATA_REPO").strip()
        if not repo_full:
            repo = _env("GITHUB_REPO").strip()
            owner = _env("GITHUB_OWNER").strip()
            if "/" in repo:
                repo_full = repo
            elif owner and repo:
                repo_full = f"{owner}/{repo}"
            else:
                repo_full = repo  # last attempt; will error if invalid

        self.repo = repo_full

        if not self.token or not self.repo or "/" not in self.repo:
            raise RuntimeError(
                "Missing/invalid GitHub config. Need GITHUB_TOKEN and GITHUB_REPO (owner/repo) "
                "or GITHUB_OWNER + GITHUB_REPO (repo name)."
            )

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

        # SHA conflict can happen on concurrent writes; refetch and retry once
        if r.status_code == 409:
            time.sleep(0.6)
            _, new_sha = self.get_json(path)
            if new_sha and sha != new_sha:
                body["sha"] = new_sha
                r = requests.put(url, headers=self._headers, json=body, timeout=25)

        r.raise_for_status()
        return r.json()

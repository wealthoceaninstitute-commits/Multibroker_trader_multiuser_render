# auth/github_store.py
import os, json, base64, requests

GITHUB_OWNER  = os.getenv("GITHUB_REPO_OWNER") or "wealthoceaninstitute-commits"
GITHUB_REPO   = os.getenv("GITHUB_REPO_NAME")  or "Multiuser_clients"
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN", "")

def _headers():
    h = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h

def _contents_url(path: str):
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"

def github_read_json(path: str):
    url = f"{_contents_url(path)}?ref={GITHUB_BRANCH}"
    r = requests.get(url, headers=_headers())
    if r.status_code != 200:
        return None
    content = base64.b64decode(r.json()["content"]).decode()
    return json.loads(content)

def github_list_dir(path: str):
    url = f"{_contents_url(path)}?ref={GITHUB_BRANCH}"
    r = requests.get(url, headers=_headers())
    return r.json() if r.status_code == 200 else []

def github_write_json(path: str, data: dict):
    url = _contents_url(path)
    r = requests.get(url, headers=_headers())
    sha = r.json().get("sha") if r.status_code == 200 else None

    payload = {
        "message": f"save {path}",
        "content": base64.b64encode(
            json.dumps(data, indent=4).encode()
        ).decode(),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    w = requests.put(url, headers=_headers(), json=payload)
    if w.status_code not in (200, 201):
        raise RuntimeError(w.text)

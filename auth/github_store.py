
import requests, base64, json, os

GITHUB_OWNER  = os.getenv("GITHUB_REPO_OWNER") or "wealthoceaninstitute-commits"
GITHUB_REPO   = os.getenv("GITHUB_REPO_NAME")  or "Multiuser_clients"
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_TOKEN  = os.getenv("GITHUB_TOKEN", "")

def _headers():
    h = {"Accept": "application/vnd.github+json"}
    if GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {GITHUB_TOKEN}"
    return h

def _contents_url(rel_path: str) -> str:
    rp = (rel_path or "").lstrip("/")
    return f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{rp}"

def github_read_json(rel_path: str):
    url = f"{_contents_url(rel_path)}?ref={GITHUB_BRANCH}"
    r = requests.get(url, headers=_headers(), timeout=20)
    if r.status_code != 200:
        return None
    j = r.json()
    content = base64.b64decode(j.get("content","")).decode("utf-8","ignore")
    try:
        return json.loads(content)
    except Exception:
        return None

def github_list_dir(rel_dir: str):
    url = f"{_contents_url(rel_dir)}?ref={GITHUB_BRANCH}"
    r = requests.get(url, headers=_headers(), timeout=20)
    if r.status_code != 200:
        return []
    return r.json() or []

def github_write_json(rel_path: str, data: dict):
    url = _contents_url(rel_path)
    # check existing
    r = requests.get(url, headers=_headers(), timeout=20)
    sha = r.json().get("sha") if r.status_code == 200 else None

    payload = {
        "message": f"save {rel_path}",
        "content": base64.b64encode(json.dumps(data, indent=4).encode()).decode(),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    w = requests.put(url, headers=_headers(), json=payload, timeout=20)
    if w.status_code not in (200, 201):
        raise RuntimeError(w.text)

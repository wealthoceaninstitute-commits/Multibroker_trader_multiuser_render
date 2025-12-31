import os, json, base64, requests

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_OWNER = os.getenv("GITHUB_REPO_OWNER", "wealthoceaninstitute-commits")
GITHUB_REPO  = os.getenv("GITHUB_REPO_NAME", "Multiuser_clients")
BRANCH = os.getenv("GITHUB_BRANCH", "main")

def github_write_json(path: str, data: dict):
    url = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/contents/{path}"

    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }

    content = base64.b64encode(
        json.dumps(data, indent=2).encode()
    ).decode()

    payload = {
        "message": f"create {path}",
        "content": content,
        "branch": BRANCH,
    }

    r = requests.put(url, headers=headers, json=payload)
    if r.status_code not in (200, 201):
        raise Exception(r.text)

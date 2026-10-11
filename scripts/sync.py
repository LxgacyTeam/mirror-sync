
import base64
import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

GH_ORG = "LxgacyTeam"
CB_ORG = "LxgacyTeam"
CB_USER = os.environ["CODEBERG_USER"]
CB_TOKEN = os.environ["CODEBERG_TOKEN"]

GH_API = "https://api.github.com"
CB_API = "https://codeberg.org/api/v1"

SKIP = {"mirror-sync"}


def api(method, url, token=None, data=None):
    headers = {
        "Accept": "application/json",
        "User-Agent": "legacyteam-backup",
    }
    if token:
        headers["Authorization"] = f"token {token}"

    body = None
    if data is not None:
        body = json.dumps(data).encode()
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url, data=body, headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise


def github_repositories():
    page = 1

    while True:
        url = (
            f"{GH_API}/orgs/{GH_ORG}/repos"
            f"?type=public&per_page=100&page={page}"
        )
        repos = api("GET", url)

        if repos is None:
            raise RuntimeError("GitHub organization not found")

        if not repos:
            break

        for repo in repos:
            if repo["name"] not in SKIP and not repo["archived"]:
                yield repo

        page += 1


def has_main(repo_name):
    url = f"https://github.com/{GH_ORG}/{repo_name}.git"
    result = subprocess.run(
        ["git", "ls-remote", "--exit-code", "--heads", url, "main"],
        capture_output=True,
        text=True,
    )

    if result.returncode == 2:
        return False

    if result.returncode != 0:
        raise RuntimeError(result.stderr)

    return True


def ensure_codeberg_repo(repo):
    name = repo["name"]
    encoded_org = urllib.parse.quote(CB_ORG, safe="")
    encoded_name = urllib.parse.quote(name, safe="")

    existing = api(
        "GET",
        f"{CB_API}/repos/{encoded_org}/{encoded_name}",
        CB_TOKEN,
    )

    if existing is not None:
        if existing["owner"]["login"].lower() != CB_ORG.lower():
            raise RuntimeError("Unexpected Codeberg repository owner")
        if existing["empty"] is False:
            print(f"Existing Codeberg repo: {name}")
        return

    print(f"Creating Codeberg repo: {name}")

    api(
        "POST",
        f"{CB_API}/orgs/{encoded_org}/repos",
        CB_TOKEN,
        {
            "name": name,
            "description": repo.get("description") or "",
            "private": False,
            "auto_init": False,
        },
    )


def sync(repo, workdir, askpass):
    name = repo["name"]
    source = f"https://github.com/{GH_ORG}/{name}.git"
    target = f"https://codeberg.org/{CB_ORG}/{name}.git"
    destination = workdir / f"{name}.git"

    print(f"Syncing {name}", flush=True)

    subprocess.run(
        [
            "git", "clone", "--bare",
            "--single-branch", "--branch", "main",
            source, str(destination),
        ],
        check=True,
    )

    env = os.environ.copy()
    env["GIT_ASKPASS"] = str(askpass)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["CB_USER_FOR_GIT"] = CB_USER
    env["CB_TOKEN_FOR_GIT"] = CB_TOKEN

    subprocess.run(
        [
            "git", "-C", str(destination),
            "push", target,
            "refs/heads/main:refs/heads/main",
        ],
        check=True,
        env=env,
    )


def main():
    failures = []

    with tempfile.TemporaryDirectory() as temp:
        workdir = Path(temp)
        askpass = workdir / "askpass.sh"

        askpass.write_text(
            '#!/bin/sh\n'
            'case "$1" in\n'
            '  *Username*) printf "%s\\n" "$CB_USER_FOR_GIT" ;;\n'
            '  *Password*) printf "%s\\n" "$CB_TOKEN_FOR_GIT" ;;\n'
            'esac\n'
        )
        askpass.chmod(0o700)

        for repo in github_repositories():
            name = repo["name"]

            try:
                if not has_main(name):
                    print(f"Skipping {name}: no main")
                    continue

                ensure_codeberg_repo(repo)
                sync(repo, workdir, askpass)

            except Exception as exc:
                failures.append(name)
                print(f"FAILED {name}: {exc}", flush=True)

    if failures:
        raise SystemExit(
            "Failed repositories: " + ", ".join(failures)
        )

    print("All repositories synchronized successfully")


if __name__ == "__main__":
    main()

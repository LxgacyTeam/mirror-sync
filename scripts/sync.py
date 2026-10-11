import json
import os
import subprocess
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from readme_links import adapt_readmes

GH_USER = "LxgacyTeam"
CB_USER = os.environ["CODEBERG_USER"]
CB_TOKEN = os.environ["CODEBERG_TOKEN"]

GH_API = "https://api.github.com"
CB_API = "https://codeberg.org/api/v1"

SKIP = {"mirror-sync"}


def api(method, url, token=None, data=None):
    headers = {
        "Accept": "application/json",
        "User-Agent": "lxgacyteam-backup",
    }

    if token:
        headers["Authorization"] = f"token {token}"

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"

    request = urllib.request.Request(
        url, data=body, headers=headers, method=method
    )

    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code == 404 and method == "GET":
            return None
        raise


def github_repositories():
    page = 1

    while True:
        url = (
            f"{GH_API}/users/{GH_USER}/repos"
            f"?type=owner&per_page=100&page={page}"
        )

        repos = api("GET", url)

        if repos is None:
            raise RuntimeError("GitHub user not found")

        if not repos:
            break

        for repo in repos:
            if (
                repo["name"] not in SKIP
                and not repo["private"]
                and not repo["archived"]
                and repo["owner"]["login"].lower() == GH_USER.lower()
            ):
                yield repo

        page += 1


def git(*args, cwd=None, env=None):
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def has_main(name):
    url = f"https://github.com/{GH_USER}/{name}.git"

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

    owner = urllib.parse.quote(CB_USER, safe="")
    encoded_name = urllib.parse.quote(name, safe="")

    existing = api(
        "GET",
        f"{CB_API}/repos/{owner}/{encoded_name}",
        CB_TOKEN,
    )

    if existing is not None:
        if existing["owner"]["login"].lower() != CB_USER.lower():
            raise RuntimeError("Unexpected repository owner")
        if existing.get("private"):
            raise RuntimeError(
                f"{name}: Codeberg repo is private; expected public"
            )
        print(f"Existing Codeberg repo: {name}", flush=True)
        return

    print(f"Creating Codeberg repo: {name}", flush=True)

    created = api(
        "POST",
        f"{CB_API}/user/repos",
        CB_TOKEN,
        {
            "name": name,
            "description": repo.get("description") or "",
            "private": False,
            "auto_init": False,
            "default_branch": "main",
        },
    )

    if created is None or created.get("name") != name:
        raise RuntimeError(f"Failed to create {name}")



def sync(repo, workdir, askpass):
    name = repo["name"]

    source = f"https://github.com/{GH_USER}/{name}.git"
    target = f"https://codeberg.org/{CB_USER}/{name}.git"

    destination = workdir / name

    print(f"Syncing {name}", flush=True)

    git(
        "clone",
        "--single-branch",
        "--branch", "main",
        source,
        str(destination),
    )

    source_sha = git(
        "rev-parse", "HEAD",
        cwd=destination,
    )

    changed_files = adapt_readmes(name, destination)

    if changed_files:
        print(
            f"Adapted README files: {', '.join(changed_files)}",
            flush=True,
        )

        git(
            "add", "--", *changed_files,
            cwd=destination,
        )

        git(
            "config", "user.name",
            "Codeberg Mirror Bot",
            cwd=destination,
        )

        git(
            "config", "user.email",
            "mirror-bot@users.noreply.github.com",
            cwd=destination,
        )

        git(
            "commit",
            "-m", "docs: adapt README links for Codeberg",
            cwd=destination,
        )

    expected_sha = git(
        "rev-parse", "HEAD",
        cwd=destination,
    )

    env = os.environ.copy()
    env["GIT_ASKPASS"] = str(askpass)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["CB_USER_FOR_GIT"] = CB_USER
    env["CB_TOKEN_FOR_GIT"] = CB_TOKEN

    remote_result = git(
        "ls-remote",
        target,
        "refs/heads/main",
        cwd=destination,
        env=env,
    )

    remote_sha = (
        remote_result.split()[0]
        if remote_result
        else ""
    )

    if remote_sha == expected_sha:
        print(f"Already up to date: {name}", flush=True)
        return

    if remote_sha:
        print(
            f"{name}: replacing Codeberg main "
            f"({remote_sha[:12]} -> {expected_sha[:12]})",
            flush=True,
        )

    git(
        "push",
        f"--force-with-lease=refs/heads/main:{remote_sha}",
        target,
        "HEAD:refs/heads/main",
        cwd=destination,
        env=env,
    )

    # Проверяем результат.
    actual_result = git(
        "ls-remote",
        target,
        "refs/heads/main",
        cwd=destination,
        env=env,
    )

    actual_sha = (
        actual_result.split()[0]
        if actual_result
        else ""
    )

    if actual_sha != expected_sha:
        raise RuntimeError(
            f"{name}: SHA mismatch after push"
        )

    print(
        f"OK {name}: "
        f"GitHub={source_sha[:12]}, "
        f"Codeberg={actual_sha[:12]}",
        flush=True,
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

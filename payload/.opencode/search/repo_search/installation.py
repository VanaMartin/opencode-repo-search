"""Explicit local Git visibility and scoped commit actions for installed files.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path


def git(root: Path, *args: str, check=True):
    return subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=check
    )


def encoded(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def write(path: Path, raw: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".install-tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def apply(root: Path, runtime: Path, action: str | None, *, dry_run=False, message=None):
    state_path = runtime / "install.json"
    state = json.loads(state_path.read_bytes())
    relative_runtime = runtime.relative_to(root)
    if action is None:
        return {
            "visibility": state.get("visibility", "undecided"),
            "choices": ["git-ignore", "git-commit"],
            "next": "Choose git-ignore for private settings or git-commit for a shared commit",
        }
    paths = sorted({*state["files"], str(relative_runtime / "install.json")})
    for name in paths:
        path = Path(name)
        if (
            path.is_absolute()
            or ".." in path.parts
            or ".git" in path.parts
            or not (root / path).resolve().is_relative_to(root)
        ):
            raise ValueError(f"Invalid managed installation path: {name}")
    specifications = [":(literal)" + name for name in paths]
    tracked = git(root, "ls-files", "-z", "--", *specifications).stdout.split("\0")
    if action == "git-ignore" and any(tracked):
        raise ValueError(
            "Tracked integration files cannot be ignored. Install a private override with "
            "install.py REPOSITORY git-ignore; tracked settings remain untouched."
        )
    if action == "git-commit":
        mixed = ["AGENTS.md", state.get("config", "")]
        conflicts = set(state.get("git_conflicts", []))
        for name in mixed:
            if name in state["files"] and (root / name).is_file():
                if hashlib.sha256((root / name).read_bytes()).hexdigest() != state["files"][name]:
                    conflicts.add(name)
        for name in conflicts:
            if git(root, "diff", "HEAD", "--name-only", "--", ":(literal)" + name).stdout:
                raise ValueError(
                    f"{name} has unrelated local edits; "
                    "resolve them before committing the integration"
                )
    exclude = Path(git(root, "rev-parse", "--git-path", "info/exclude").stdout.strip())
    exclude = root / exclude
    original = exclude.read_text() if exclude.exists() else ""
    key = hashlib.sha256(str(relative_runtime).encode()).hexdigest()[:12]
    start, end = f"# repo-search:{key}:start", f"# repo-search:{key}:end"
    pattern = re.compile(r"(?m)^" + re.escape(start) + r"\n.*?^" + re.escape(end) + r"\n?", re.S)
    if (start in original or end in original) and not pattern.search(original):
        raise ValueError("Local Git excludes have an incomplete repo-search block")
    updated = pattern.sub("", original)
    if action == "git-ignore":

        def escape(name):
            return "".join("\\" + char if char in "\\ !#*?[]" else char for char in name)

        block = start + "\n" + "\n".join("/" + escape(name) for name in paths) + "\n" + end + "\n"
        updated += ("\n" if updated and not updated.endswith("\n") else "") + block
    result = {
        "action": action,
        "visibility": "private" if action == "git-ignore" else "shared",
        "files": paths,
        "dry_run": dry_run,
    }
    if dry_run:
        return result
    settings_path = runtime / "runtime.json"
    settings = json.loads(settings_path.read_bytes())
    settings["policy_source"] = "local" if action == "git-ignore" else "upstream"
    settings["profile"] = str(relative_runtime / "profiles.json")
    raw = encoded(settings)
    state["files"][str(relative_runtime / "runtime.json")] = hashlib.sha256(raw).hexdigest()
    state["visibility"] = result["visibility"]
    write(settings_path, raw)
    write(state_path, encoded(state))
    if updated != original:
        write(exclude, updated.encode())
    if action == "git-commit":
        git(root, "add", "--force", "--", *specifications)
        changed = git(root, "diff", "--cached", "--quiet", "--", *specifications, check=False)
        if changed.returncode not in {0, 1}:
            raise ValueError(changed.stderr)
        if changed.returncode:
            committed = git(
                root,
                "commit",
                "--only",
                "-m",
                message or "configure repository search",
                "--",
                *specifications,
                check=False,
            )
            if committed.returncode:
                raise ValueError(
                    "Git commit failed; installation remains prepared:\n"
                    + committed.stdout
                    + committed.stderr
                )
        result["commit"] = git(root, "rev-parse", "HEAD").stdout.strip()
        result["next"] = "Publish the policy to the configured source branch, then run setup.sh"
    else:
        result["next"] = "Run setup.sh; source is upstream and policy is pinned locally"
    return result


def main(runtime: Path, arguments):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=["git-ignore", "git-commit"])
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--message")
    args = parser.parse_args(arguments)
    root = Path(git(runtime, "rev-parse", "--show-toplevel").stdout.strip())
    try:
        result = apply(root, runtime, args.action, dry_run=args.dry_run, message=args.message)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Initialization failed: {error}\n")
    print(json.dumps(result, indent=2))

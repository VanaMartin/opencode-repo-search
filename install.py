"""Install project-local search files and merge only the managed MCP entries.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

BUNDLE = Path(__file__).resolve().parent
PAYLOAD = BUNDLE / "payload"
RUNTIME = Path(".opencode/search")
STATE = RUNTIME / "install.json"
START = "<!-- repo-search:start -->"
END = "<!-- repo-search:end -->"


def encoded(value) -> bytes:
    return (json.dumps(value, indent=2) + "\n").encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def install(args) -> dict:
    requested = args.repository.expanduser().resolve()
    root = Path(git(requested, "rev-parse", "--show-toplevel"))
    if root != requested:
        raise ValueError("Choose the Git worktree root as the installation directory")
    state_path = root / STATE
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    runtime_path = root / RUNTIME / "runtime.json"
    saved = (
        json.loads(runtime_path.read_text())
        if args.configure_only and runtime_path.exists()
        else {}
    )
    remote = args.remote or saved.get("remote", "origin")
    git(root, "remote", "get-url", remote)
    branch = args.branch or saved.get("branch")
    if branch is None:
        try:
            branch = git(root, "symbolic-ref", "--short", f"refs/remotes/{remote}/HEAD")
            branch = branch.removeprefix(remote + "/")
        except subprocess.CalledProcessError:
            branch = "main"
    subprocess.run(
        ["git", "check-ref-format", "refs/heads/" + branch], check=True, capture_output=True
    )
    profile_path = root / RUNTIME / "profiles.json"
    if args.configure_only:
        if not profile_path.is_file():
            raise ValueError("--configure-only needs an existing installation")
        profile = json.loads(profile_path.read_text())
    else:
        source_profile = args.profile or PAYLOAD / RUNTIME / "profiles.json"
        profile = json.loads(source_profile.read_text())
    corpora = (
        args.corpora.split(",")
        if args.corpora
        else [name for name, policy in profile["corpora"].items() if policy["enabled"]]
    )
    if not corpora or any(name not in profile["corpora"] for name in corpora):
        raise ValueError("Select existing corpus names with --corpora name1,name2")
    for name, policy in profile["corpora"].items():
        policy["enabled"] = name in corpora
    subprocess.run(
        [sys.executable, str(PAYLOAD / RUNTIME / "run.py"), "validate-profile"],
        input=encoded(profile),
        check=True,
        capture_output=True,
    )
    settings = {"remote": remote, "branch": branch}
    if args.db:
        settings["db"] = str(args.db.expanduser().resolve())
    elif saved.get("db"):
        settings["db"] = saved["db"]
    servers = {}
    for name in corpora:
        policy = profile["corpora"][name]
        command = [
            "uv",
            "run",
            "--project",
            ".opencode/search",
            "--python",
            "3.12",
            "--frozen",
            "python",
            ".opencode/search/run.py",
            "mcp",
            "--corpus",
            name,
            "--remote",
            remote,
            "--branch",
            branch,
        ]
        if settings.get("db"):
            command += ["--db", settings["db"]]
        servers[policy["server"]] = {
            "type": "local",
            "cwd": ".",
            "command": command,
            "timeout": {"startup": 900000},
        }
    fragment = {"mcp": {"servers": servers}}
    candidates = [
        root / ".opencode/opencode.jsonc",
        root / ".opencode/opencode.json",
        root / "opencode.jsonc",
        root / "opencode.json",
    ]
    config_path = next((path for path in candidates if path.exists()), root / "opencode.json")
    config = None
    if not args.fragment_only:
        try:
            config = (
                json.loads(config_path.read_text())
                if config_path.exists()
                else {"$schema": "https://opencode.ai/config.json"}
            )
        except json.JSONDecodeError as error:
            raise ValueError(
                "Existing config uses JSONC syntax. Use --fragment-only, then manually merge "
                ".opencode/search/mcp.fragment.json into it."
            ) from error
        existing = config.setdefault("mcp", {}).setdefault("servers", {})
        managed = set(previous.get("servers", []))
        for name in managed:
            original = previous.get("server_config", {}).get(name)
            if name in existing and original is not None and existing[name] != original:
                raise ValueError(f"Managed MCP {name} was customized; merge the fragment manually")
        for name, server in servers.items():
            if name in existing and existing[name] != server and name not in managed:
                raise ValueError(
                    f"MCP {name} already exists; choose another server name in the profile"
                )
        for name in managed - set(servers):
            existing.pop(name, None)
        existing.update(servers)
    files = {}
    if not args.configure_only:
        for source in sorted(PAYLOAD.rglob("*")):
            if (
                not source.is_file()
                or any(
                    part in {".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}
                    for part in source.relative_to(PAYLOAD).parts
                )
                or source.suffix == ".pyc"
            ):
                continue
            relative = source.relative_to(PAYLOAD)
            if relative != RUNTIME / "profiles.json":
                files[relative] = source.read_bytes()
        files[RUNTIME / "profiles.json"] = encoded(profile)
    else:
        files[RUNTIME / "profiles.json"] = encoded(profile)
    files[RUNTIME / "runtime.json"] = encoded(settings)
    files[RUNTIME / "mcp.fragment.json"] = encoded(fragment)
    files[RUNTIME / "LICENSE"] = (BUNDLE / "LICENSE").read_bytes()
    if config is not None:
        files[config_path.relative_to(root)] = encoded(config)
    guidance = (PAYLOAD / RUNTIME / "AGENTS.snippet.md").read_text().strip()
    agents_path = root / "AGENTS.md"
    current = agents_path.read_text() if agents_path.exists() else ""
    block = f"{START}\n{guidance}\n{END}"
    if START in current:
        pattern = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
        if not pattern.search(current):
            raise ValueError("AGENTS.md has an incomplete repo-search block")
        updated = pattern.sub(lambda _: block, current)
    else:
        updated = current.rstrip() + ("\n\n" if current.strip() else "") + block + "\n"
    files[Path("AGENTS.md")] = updated.encode()
    generated = {
        RUNTIME / "profiles.json",
        RUNTIME / "runtime.json",
        RUNTIME / "mcp.fragment.json",
        Path("AGENTS.md"),
        config_path.relative_to(root),
    }
    for relative, raw in files.items():
        destination = root / relative
        if not destination.resolve().is_relative_to(root):
            raise ValueError(f"Installation path resolves outside the worktree: {relative}")
        if destination.exists() and destination.read_bytes() != raw:
            if relative in generated:
                if relative == RUNTIME / "profiles.json" and not args.configure_only:
                    raise ValueError("Existing customized profile: use --configure-only to keep it")
                continue
            raise ValueError(f"Existing file differs: {relative}; inspect it before upgrading")
    state = {
        "format": "repo-search-install-v1",
        "servers": list(servers),
        "server_config": servers,
        "config": str(config_path.relative_to(root)) if config is not None else "manual-fragment",
        "files": {str(path): digest(raw) for path, raw in files.items()},
    }
    if not state_path.resolve().is_relative_to(root):
        raise ValueError("Installation state resolves outside the worktree")
    if not args.dry_run:
        for relative, raw in files.items():
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + ".install-tmp")
            temporary.write_bytes(raw)
            temporary.replace(destination)
        state_path.write_bytes(encoded(state))
    return {
        "mode": "dry-run" if args.dry_run else "installed",
        "root": str(root),
        "branch": branch,
        "corpora": corpora,
        "servers": list(servers),
        "config": state["config"],
        "files": len(files),
        "next": "Customize profiles, commit and publish to the source branch, then run setup.sh",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("repository", type=Path)
    parser.add_argument(
        "--corpora", help="Comma-separated corpus names; defaults to enabled profiles"
    )
    parser.add_argument(
        "--remote", help="Defaults to origin; reconfiguration preserves the installed remote"
    )
    parser.add_argument("--branch", help="Defaults to remote HEAD, or main if it is unknown")
    parser.add_argument(
        "--db", type=Path, help="Explicit database shared by this repository's worktrees"
    )
    parser.add_argument(
        "--profile", type=Path, help="Use a customized profile on initial installation"
    )
    parser.add_argument(
        "--configure-only", action="store_true", help="Keep installed scripts/profile"
    )
    parser.add_argument(
        "--fragment-only", action="store_true", help="Generate MCP JSON for manual merging"
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        result = install(args)
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"Installation failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()

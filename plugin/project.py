"""Initialize small repository settings for the native package plugin.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE / "payload/.opencode/search"))

from migration import installations, migrate  # noqa: E402
from repo_search.git_source import MainSource  # noqa: E402
from repo_search.installation import apply, encoded, git, write  # noqa: E402
from repo_search.settings import validate_profile  # noqa: E402
from suggestions import inspect_repository  # noqa: E402

DIRECTORY = Path(".opencode/search-package")


def completion_guidance(result: dict, profile: dict, config: dict) -> dict:
    """Suggest follow-up actions without connecting MCPs or provisioning Python."""
    enabled = {name: policy for name, policy in profile["corpora"].items() if policy["enabled"]}
    path = config["profile"]
    upstream = f"{config['remote']}/{config['branch']}"
    steps = [f"Review {path}: include/exclude paths and enable only the corpora you need."]
    if config["policy_source"] == "upstream":
        steps.append(
            f"Ensure the shared policy at {path} is published on {upstream} before indexing; "
            "publish any new shared policy commit through your usual Git workflow. "
            "Initialization never pushes."
        )
    if enabled:
        servers = ", ".join(policy["server"] for policy in enabled.values())
        steps.extend(
            [
                f"/mcps — confirm the enabled search MCPs ({servers}) connect after reload. "
                "The first connection may take several minutes to download the runtime/model.",
                f"/search-sync — build or refresh all enabled corpora ({', '.join(enabled)}) "
                f"from committed {upstream} source, not working-tree changes.",
                "/search-status — check ready_for_queries: true before searching; "
                "otherwise inspect refresh.phase and any refresh error. "
                "An MCP connection alone does not mean the first index is ready.",
                'Ask: "Use repo-knowledge-search to search the enabled corpora for <your topic>."',
            ]
        )
    else:
        steps.append(
            f"No corpora are enabled, so no search MCP is registered. Enable a corpus in {path}; "
            "after automatic reload, use /mcps, /search-sync and /search-status."
        )
    result["next"] = (
        (
            "Settings saved privately using .git/info/exclude (.gitignore is unchanged)."
            if result["visibility"] == "private"
            else "Shared settings saved in a local commit."
        )
        + " OpenCode reloads valid settings automatically; "
        "connection/index readiness is not yet checked."
    )
    result["next_steps"] = steps
    return result


def initialize(arguments: list[str]) -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", nargs="?", choices=["git-ignore", "git-commit"])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--remote")
    parser.add_argument("--branch")
    parser.add_argument("--db")
    parser.add_argument("--corpora", help="Comma-separated enabled corpus names")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--message")
    parser.add_argument("--migrate", action="store_true", help="Adopt installer policy in place")
    args = parser.parse_args(arguments)
    root = Path(git(args.root, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    directory = root / DIRECTORY
    state_path = directory / "install.json"
    previous = json.loads(state_path.read_bytes()) if state_path.exists() else {}
    if args.migrate:
        result = migrate(root, args, previous)
        if args.action and not args.dry_run:
            profile = json.loads((root / result["settings"]["profile"]).read_bytes())
            # Retain adoption-specific daemon/reconnection advice as well.
            next_step = result["next"]
            completion_guidance(result, profile, result["settings"])
            result["next_steps"].insert(0, next_step)
        return result
    if not args.action:
        settings_path = directory / "runtime.json"
        saved = json.loads(settings_path.read_bytes()) if settings_path.exists() else {}
        source = root / saved.get("profile", str(DIRECTORY / "profiles.json"))
        if not source.exists():
            source = PACKAGE / "payload/.opencode/search/profiles.json"
        profile = json.loads(source.read_bytes())
        validate_profile(profile)
        return {
            "visibility": previous.get("visibility", "undecided"),
            "choices": ["git-ignore", "git-commit"],
            "directory": str(directory),
            "next": "Choose git-ignore for local policy or git-commit for shared policy",
            "installer_integrations": installations(root),
            "inspection": inspect_repository(root, profile, saved),
        }
    if installations(root):
        raise ValueError("Existing installer integration found; use init --migrate to adopt it")
    profile_path = directory / "profiles.json"
    source = (
        profile_path
        if profile_path.exists()
        else PACKAGE / "payload/.opencode/search/profiles.json"
    )
    profile = json.loads(source.read_bytes())
    if args.corpora is not None:
        names = set(args.corpora.split(","))
        if names - profile["corpora"].keys():
            raise ValueError("Unknown corpus name; add custom corpus policy before enabling it")
        for name, policy in profile["corpora"].items():
            policy["enabled"] = name in names
    validate_profile(profile)
    settings_path = directory / "runtime.json"
    settings = json.loads(settings_path.read_bytes()) if settings_path.exists() else {}
    settings["remote"] = args.remote or settings.get("remote", "origin")
    remote = settings["remote"]
    branch = args.branch or settings.get("branch")
    if not branch:
        default = git(root, "symbolic-ref", "--quiet", f"refs/remotes/{remote}/HEAD", check=False)
        branch = default.stdout.strip().removeprefix(f"refs/remotes/{remote}/") or "main"
    # Validate Git settings without fetching or reading a not-yet-written policy.
    MainSource.discover(root, remote=remote, branch=branch)
    settings.update(
        branch=branch,
        profile=str(DIRECTORY / "profiles.json"),
        policy_source="local" if args.action == "git-ignore" else "upstream",
    )
    if args.db:
        settings["db"] = str(Path(args.db).expanduser().resolve())
    files = {"profiles.json": encoded(profile), "runtime.json": encoded(settings)}
    state = {
        "format": "repo-search-install-v1",
        "layout": "package",
        "visibility": previous.get("visibility", "undecided"),
        "files": {
            str(DIRECTORY / name): hashlib.sha256(raw).hexdigest() for name, raw in files.items()
        },
    }
    if args.action == "git-ignore":
        tracked = git(root, "ls-files", "--", ":(literal)" + str(DIRECTORY)).stdout
        if tracked:
            raise ValueError("Package settings are tracked; Git cannot ignore them")
    for name in (*files, "install.json"):
        if not (directory / name).resolve().is_relative_to(root):
            raise ValueError("Package settings resolve outside the worktree")
    if args.dry_run:
        return {
            "action": args.action,
            "dry_run": True,
            "directory": str(directory),
            "files": list(state["files"]),
            "inspection": inspect_repository(root, profile, settings),
        }
    for name, raw in files.items():
        write(directory / name, raw)
    write(state_path, encoded(state))
    result = apply(root, directory, args.action, message=args.message)
    result["inspection"] = inspect_repository(root, profile, settings)
    return completion_guidance(result, profile, settings)


def settings(root: Path) -> tuple[Path, dict]:
    root = Path(git(root, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    path = root / DIRECTORY / "runtime.json"
    if not path.is_file():
        raise ValueError("Repository search is not initialized; run /search-init first")
    config = json.loads(path.read_bytes())
    validate_profile(json.loads((root / config["profile"]).read_bytes()))
    return root, config

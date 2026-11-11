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

from configuration import (  # noqa: E402
    DIRECTORY,
    FORMAT,
    local_binding,
    locations,
    optional,
    provenance,
    publish,
    repository_lock,
    repository_path,
    resolve,
)
from migration import installations, migrate  # noqa: E402
from repo_search.git_source import MainSource  # noqa: E402
from repo_search.installation import apply, encoded, git, write  # noqa: E402
from repo_search.settings import validate_profile  # noqa: E402
from suggestions import inspect_repository  # noqa: E402


def completion_guidance(result: dict, profile: dict, config: dict) -> dict:
    """Suggest follow-up actions without connecting MCPs or provisioning Python."""
    enabled = {name: policy for name, policy in profile["corpora"].items() if policy["enabled"]}
    path = config["profile"]
    review_path = (
        f"the profile object in {result['configuration']['path']}"
        if result.get("scope") == "repository"
        else path
    )
    upstream = f"{config['remote']}/{config['branch']}"
    steps = [f"Review {review_path}: include/exclude paths and enable only the corpora you need."]
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
            "No corpora are enabled, so no search MCP is registered. "
            f"Enable a corpus in {review_path}; "
            "after automatic reload, use /mcps, /search-sync and /search-status."
        )
    result["next"] = (
        (
            "Repository-private settings saved in the Git common directory; "
            "linked worktrees inherit them."
            if result.get("scope") == "repository"
            else "Settings saved privately using .git/info/exclude (.gitignore is unchanged)."
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
    parser.add_argument("--scope", choices=["worktree", "repository"])
    parser.add_argument(
        "--adopt",
        action="store_true",
        help="Explicitly adopt existing package settings into repository scope",
    )
    args = parser.parse_args(arguments)
    root, common = locations(args.root)
    effective = resolve(root)
    scope = args.scope or ("worktree" if args.migrate else effective["scope"]) or "worktree"
    if args.adopt and scope != "repository":
        raise ValueError("--adopt requires --scope repository")
    if scope == "repository":
        if args.migrate:
            raise ValueError(
                "Adopt the installer with --migrate first, then use --scope repository --adopt"
            )
        return initialize_repository(root, common, args, effective)
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
            "configuration": provenance(effective),
            "scope": "worktree",
            "scopes": ["worktree", "repository"],
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
    if not profile_path.exists() and effective["profile"] is not None:
        profile = json.loads(json.dumps(effective["profile"]))
    if args.corpora is not None:
        names = set(args.corpora.split(","))
        if names - profile["corpora"].keys():
            raise ValueError("Unknown corpus name; add custom corpus policy before enabling it")
        for name, policy in profile["corpora"].items():
            policy["enabled"] = name in names
    validate_profile(profile)
    settings_path = directory / "runtime.json"
    settings = (
        json.loads(settings_path.read_bytes())
        if settings_path.exists()
        else dict(effective["settings"] or {})
    )
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
            "scope": "worktree",
        }
    for name, raw in files.items():
        write(directory / name, raw)
    write(state_path, encoded(state))
    result = apply(root, directory, args.action, message=args.message)
    # An explicit local override supersedes a previous repository-scope adoption.
    if args.scope == "worktree" and repository_path(common).is_file():
        with repository_lock(common) as path:
            document = optional(path)
            if document.get("adoptions", {}).pop(str(root), None):
                publish(path, document)
    result["scope"] = "worktree"
    result["configuration"] = provenance(resolve(root))
    result["inspection"] = inspect_repository(root, profile, settings)
    return completion_guidance(result, profile, settings)


def settings(root: Path) -> tuple[Path, dict]:
    configuration = resolve(root)
    if configuration["settings"] is None:
        raise ValueError("Repository search is not initialized; run /search-init first")
    return Path(configuration["root"]), configuration["settings"]


def initialize_repository(root, common, args, effective):
    if args.action == "git-commit":
        raise ValueError("Repository scope is private; use git-ignore, not git-commit")
    if args.adopt and any(
        getattr(args, name) is not None for name in ("remote", "branch", "db", "corpora")
    ):
        raise ValueError("Scope adoption preserves settings; edit policy/settings after adoption")
    if installations(root):
        state = effective["installation"]
        if any(
            name not in state.get("migration", {}).get("sources", [])
            for name in installations(root)
        ):
            raise ValueError(
                "Existing installer integration found; use init --migrate to adopt it first"
            )
    path = repository_path(common)

    def proposal():
        shared = optional(path)
        local = optional(root / DIRECTORY / "runtime.json")
        binding = local_binding(root, local) if local else None
        adopted = shared and shared.get("adoptions", {}).get(str(root)) == binding
        if (
            local
            and not adopted
            and not args.adopt
            and (shared is None or effective["source"] == "worktree-private")
        ):
            raise ValueError(
                "Existing worktree settings require explicit --scope repository --adopt"
            )
        if args.adopt and local and shared and not adopted:
            if shared["settings"] != local or shared["profile"] != json.loads(
                (root / local["profile"]).read_bytes()
            ):
                raise ValueError(
                    "Repository-private settings already exist and differ; "
                    "reconcile before adoption"
                )
        take_local = args.adopt and local and not adopted
        config = dict(local if take_local else shared["settings"] if shared else {})
        if take_local:
            profile = json.loads((root / local["profile"]).read_bytes())
            state = optional(root / DIRECTORY / "install.json") or {}
        elif shared:
            profile, state = shared["profile"], shared.get("installation", {})
        else:
            profile = json.loads((PACKAGE / "payload/.opencode/search/profiles.json").read_bytes())
            state = {}
        if args.corpora is not None:
            names = set(args.corpora.split(","))
            if names - profile["corpora"].keys():
                raise ValueError("Unknown corpus name; add custom corpus policy before enabling it")
            for name, policy in profile["corpora"].items():
                policy["enabled"] = name in names
        validate_profile(profile)
        config["remote"] = args.remote or config.get("remote", "origin")
        branch = args.branch or config.get("branch") or ("main" if take_local else None)
        if not branch:
            default = git(
                root,
                "symbolic-ref",
                "--quiet",
                f"refs/remotes/{config['remote']}/HEAD",
                check=False,
            )
            branch = (
                default.stdout.strip().removeprefix(f"refs/remotes/{config['remote']}/") or "main"
            )
        config.update(
            branch=branch,
            profile=config.get("profile", str(DIRECTORY / "profiles.json")),
            policy_source=config.get(
                "policy_source", "upstream" if take_local or shared else "local"
            ),
        )
        MainSource.discover(root, remote=config["remote"], branch=branch, profile=config["profile"])
        if args.db:
            config["db"] = str(Path(args.db).expanduser().resolve())
        document = {
            "format": FORMAT,
            "origin_worktree": shared["origin_worktree"] if shared else str(root),
            "settings": config,
            "profile": profile,
            "installation": {**state, "visibility": "private", "scope": "repository"},
            "adoptions": dict(shared.get("adoptions", {})) if shared else {},
        }
        if args.adopt and binding:
            document["adoptions"][str(root)] = binding
        return document

    # Inspection/dry-run must not even create the lock/configuration directory.
    if args.action and not args.dry_run:
        with repository_lock(common):
            document = proposal()
            publish(path, document)
    else:
        document = proposal()
    config, profile = document["settings"], document["profile"]
    result = {
        "scope": "repository",
        "visibility": "private",
        "directory": str(path.parent),
        "files": [str(path)],
        "dry_run": args.dry_run,
        "choices": ["git-ignore"],
        "settings": config,
        "inspection": inspect_repository(root, profile, config),
        "configuration": provenance(resolve(root))
        if args.action and not args.dry_run
        else {
            **provenance(effective),
            "proposed_source": "repository-private",
            "proposed_path": str(path),
        },
    }
    if not args.action or args.dry_run:
        result["next"] = (
            "Choose git-ignore --scope repository to share private settings across linked worktrees"
        )
        return result
    result["action"] = args.action
    return completion_guidance(result, profile, config)

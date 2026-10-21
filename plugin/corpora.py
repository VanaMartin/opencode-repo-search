"""Preview and apply scoped corpus edits with explicit publication and sync.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import argparse
import copy
import fcntl
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from migration import jsonc, local_path
from project import DIRECTORY, PACKAGE, settings
from repo_search.installation import encoded, git, write
from repo_search.settings import validate_profile
from suggestions import inspect_repository

LISTS = {"include", "exclude", "extensions", "extensionless_files"}
FIELDS = LISTS | {"enabled", "server", "parser", "description", "source_kind"}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def validate_spec(spec):
    if not isinstance(spec, dict) or not spec or spec.keys() - FIELDS:
        raise ValueError("Supply a nonempty corpus object with supported policy fields only")
    for name, value in spec.items():
        if name in LISTS:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise ValueError(f"{name} must be a list of strings")
            if name != "extensions" and any(
                not item
                or Path(item).is_absolute()
                or ".." in Path(item).parts
                or ".git" in Path(item).parts
                or "\\" in item
                or re.match(r"^[A-Za-z]:", item)
                for item in value
            ):
                raise ValueError(f"{name} patterns must stay within the repository")
            if name == "extensions" and any(
                not re.fullmatch(r"\.[A-Za-z0-9_+-]+", item)
                or item.lower() in {".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg"}
                for item in value
            ):
                raise ValueError(
                    "Select UTF-8 text extensions; PDF/binary ingestion is not supported"
                )
        elif name == "enabled":
            if not isinstance(value, bool):
                raise ValueError("enabled must be true or false")
        elif not isinstance(value, str):
            raise ValueError(f"{name} must be a string")


def propose(profile, args, spec):
    validate_spec(spec)
    if not re.fullmatch(r"[a-z][a-z0-9_]*", args.name):
        raise ValueError("Corpus names must be lowercase identifiers")
    exists = args.name in profile["corpora"]
    if args.operation == "add" and exists:
        raise ValueError("Corpus already exists; use corpus update")
    if args.operation == "update" and not exists:
        raise ValueError("Unknown corpus; use corpus add")
    candidate = copy.deepcopy(profile)
    policy = candidate["corpora"].setdefault(args.name, {})
    for name, value in spec.items():
        if exists and name in {"server", "parser"} and value != policy[name]:
            raise ValueError(
                "Changing parser/server requires a new corpus; existing identities are preserved"
            )
        if exists and name in LISTS and not args.replace_lists:
            value = list(dict.fromkeys([*policy.get(name, []), *value]))
        policy[name] = value
    validate_profile(candidate)
    for name in args.exclude_from:
        if name == args.name or name not in candidate["corpora"]:
            raise ValueError("--exclude-from must name a different existing corpus")
        other = candidate["corpora"][name]
        other["exclude"] = list(dict.fromkeys([*other["exclude"], *policy["include"]]))
    validate_profile(candidate)
    return candidate


def check_servers(root, old, candidate):
    managed = {policy["server"] for policy in old["corpora"].values()}
    new = {policy["server"] for policy in candidate["corpora"].values()} - managed
    for name in (
        "opencode.json",
        "opencode.jsonc",
        ".opencode/opencode.json",
        ".opencode/opencode.jsonc",
    ):
        path = local_path(root, name)
        if path.exists() and new.intersection(jsonc(path).get("mcp", {}).get("servers", {})):
            raise ValueError(f"New MCP name conflicts with an existing server in {name}")


def publish(root, path, raw, config_raw, candidate, revision):
    common = Path(git(root, "rev-parse", "--git-common-dir").stdout.strip())
    lock = (
        (root / common).resolve()
        / "repo-search"
        / ("corpus-edit-" + digest(str(path).encode())[:16] + ".lock")
    )
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        current_config = local_path(root, str(DIRECTORY / "runtime.json")).read_bytes()
        if digest(current_config + b"\0" + path.read_bytes()) != revision:
            raise ValueError("Policy/settings changed since preview; inspect and preview again")
        if current_config != config_raw or path.read_bytes() != raw:
            raise ValueError("Policy/settings changed during edit")
        state_path = local_path(root, str(DIRECTORY / "install.json"))
        if path.is_symlink() or state_path.is_symlink():
            raise ValueError("Managed policy/metadata must not be symlinks")
        original_state = state_path.read_bytes()
        state = json.loads(original_state)
        if state.get("format") != "repo-search-install-v1" or not isinstance(
            state.get("files"), dict
        ):
            raise ValueError("Unsupported installation metadata; inspect it before editing corpora")
        relative = path.relative_to(root).as_posix()
        data = encoded(candidate)
        owns_profile = relative in state["files"]
        if owns_profile:
            state["files"][relative] = digest(data)
            write(state_path, encoded(state))
        try:
            write(path, data)  # Publish the complete validated profile last, in one replace.
        except OSError:
            if owns_profile:
                write(state_path, original_state)
            raise


def synchronize(root, names):
    results = {}
    for name in names:
        print(f"repo-search: syncing corpus {name}", file=sys.stderr)
        try:
            process = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGE / "plugin/launch.py"),
                    "sync",
                    "--root",
                    str(root),
                    "--corpus",
                    name,
                ],
                stdout=subprocess.PIPE,
                text=True,
                timeout=1800,
            )
            if process.returncode:
                return {
                    "state": "failed",
                    "corpus": name,
                    "results": results,
                    "error": "Sync failed; policy is applied. Inspect /search-status and stderr.",
                }
            results[name] = json.loads(process.stdout)
        except (OSError, subprocess.TimeoutExpired, ValueError) as error:
            return {"state": "failed", "corpus": name, "results": results, "error": str(error)}
    return {"state": "complete", "results": results}


def manage(arguments):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["inspect", "add", "update"])
    parser.add_argument("name", nargs="?")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--spec", type=Path, help="JSON corpus object/patch, or - for stdin")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--apply", action="store_true")
    action.add_argument("--dry-run", action="store_true")
    parser.add_argument("--expect-revision", help="Revision returned by the reviewed preview")
    parser.add_argument(
        "--replace-lists", action="store_true", help="Explicitly replace supplied lists"
    )
    parser.add_argument(
        "--exclude-from", action="append", default=[], help="Explicit overlap exclusion"
    )
    parser.add_argument(
        "--sync", action="store_true", help="Sync after apply; shared policy needs publication"
    )
    args = parser.parse_args(arguments)
    root, config = settings(args.root)
    config_raw = local_path(root, str(DIRECTORY / "runtime.json")).read_bytes()
    config = json.loads(config_raw)
    path = local_path(root, config["profile"])
    if path.is_symlink():
        raise ValueError("Managed policy must not be a symlink")
    raw = path.read_bytes()
    profile = json.loads(raw)
    validate_profile(profile)
    base_revision = digest(config_raw + b"\0" + raw)
    if args.operation == "inspect":
        if (
            args.name
            or args.spec
            or args.apply
            or args.sync
            or args.replace_lists
            or args.exclude_from
        ):
            raise ValueError("corpus inspect accepts only --root")
        return {
            "profile_path": config["profile"],
            "profile": profile,
            "settings": config,
            "revision": base_revision,
            "inspection": inspect_repository(root, profile, config),
        }
    if not args.name or args.spec is None:
        raise ValueError("Supply a corpus name and --spec JSON_FILE (or --spec -)")
    if args.apply and not args.expect_revision:
        raise ValueError("--apply requires --expect-revision from a reviewed preview")
    spec = json.load(sys.stdin) if str(args.spec) == "-" else json.loads(args.spec.read_bytes())
    candidate = propose(profile, args, spec)
    revision = digest(base_revision.encode() + b"\0" + encoded(candidate))
    if args.expect_revision and args.expect_revision != revision:
        raise ValueError(
            "Policy/settings or proposal changed since preview; inspect and preview again"
        )
    check_servers(root, profile, candidate)
    inspection = inspect_repository(root, candidate, config)
    errors = []
    for name in dict.fromkeys([args.name, *args.exclude_from]):
        if not candidate["corpora"][name]["enabled"]:
            continue
        selected = inspection["corpora"].get(name, {})
        if not selected.get("selected_files"):
            errors.append(
                f"{name}: no files selected in the inspected commit; "
                "publish source or add it disabled"
            )
        if selected.get("invalid_notes"):
            errors.append(
                f"{name}: literature notes have invalid title/Source/Pagination declarations"
            )
    changed = candidate != profile
    changed_names = [
        name
        for name, policy in candidate["corpora"].items()
        if policy != profile["corpora"].get(name)
    ]
    private = config.get("policy_source") == "local"
    enabled = [name for name, policy in candidate["corpora"].items() if policy["enabled"]]
    sync_names = (
        enabled
        if private and changed
        else [name for name in (changed_names or [args.name]) if name in enabled]
    )
    warnings = []
    if private and changed:
        warnings.append(
            "The private policy hash changes for the entire profile: enabled corpora "
            "get new table identities and may rebuild; the default database also changes. "
            "Old indexes are retained. --sync will reconcile all enabled corpora."
        )
    if inspection["overlapping_files"]:
        warnings.append(
            "Enabled corpora overlap; review ownership. --exclude-from changes another "
            "corpus only when explicitly supplied."
        )
    steps = []
    if not private:
        steps.append(
            f"Publish the shared policy to {config['remote']}/{config['branch']} using "
            "your usual Git workflow. No files were staged, committed or pushed."
        )
    steps.extend(
        [
            "/mcps — check automatic corpus registration/reconnection.",
            *[f"/search-sync --corpus {name}" for name in sync_names],
            f"/search-status --corpus {args.name} — verify ready_for_queries and freshness.",
        ]
    )
    result = {
        "operation": args.operation,
        "corpus": args.name,
        "profile_path": config["profile"],
        "revision": revision,
        "base_revision": base_revision,
        "changed": changed,
        "applied": False,
        "changes": {
            name: {"before": profile["corpora"].get(name), "after": policy}
            for name, policy in candidate["corpora"].items()
            if policy != profile["corpora"].get(name)
        },
        "inspection": inspection,
        "validation_errors": errors,
        "warnings": warnings,
        "sync_corpora": sync_names,
        "publication_required": not private,
        "sync": {"state": "preview" if args.sync else "not_requested"},
        "next": "Preview only; review the proposal and warnings before applying.",
        "next_steps": steps,
    }
    if not args.apply:
        result["next_steps"] = [
            "Resolve validation_errors and preview again before applying."
            if errors
            else f"Confirm the proposal, then use --apply --expect-revision {revision}.",
            "Only after application: check /mcps, request /search-sync if needed, "
            "and verify /search-status. Shared policy needs publication first.",
        ]
        return result
    if errors:
        raise ValueError("; ".join(errors))
    if changed:
        publish(root, path, raw, config_raw, candidate, base_revision)
    result["applied"] = True
    result["next"] = (
        "Corpus policy applied. OpenCode reloads it automatically; readiness is not yet checked."
    )
    if args.sync:
        result["sync"] = (
            {"state": "publication_required"} if not private else synchronize(root, sync_names)
        )
    return result

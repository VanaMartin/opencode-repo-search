"""Adopt installer policy in place without changing search identities.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import hashlib
import json
import re
from pathlib import Path

from repo_search.git_source import MainSource
from repo_search.installation import apply, encoded, git, write
from repo_search.settings import validate_profile
from suggestions import inspect_repository

DIRECTORY = Path(".opencode/search-package")
LAYOUTS = ("search-local", "search")
LOADER = ".opencode/plugins/repo-search-private.js"
STUB = (
    b"/**\n * SPDX-License-Identifier: BSD-3-Clause\n"
    b" * License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE\n */\n"
    b"// Registrations were adopted by opencode-repo-search; see search-package/install.json.\n"
    b'export default { id: "repo-search-private", setup() {} }\n'
)


def installations(root):
    return [
        f".opencode/{layout}"
        for layout in LAYOUTS
        if (root / ".opencode" / layout / "install.json").is_file()
    ]


def local_path(root, name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
        raise ValueError(f"Invalid installation path: {name}")
    target = root / path
    if not target.resolve().is_relative_to(root):
        raise ValueError(f"Installation path resolves outside the worktree: {name}")
    return target


def jsonc(path):
    # Parse for ownership checks only; the original configuration is never rewritten.
    text = path.read_text()
    tokens = r'"(?:[^"\\]|\\.)*"|//[^\n]*|/\*[\s\S]*?\*/'
    text = re.sub(tokens, lambda m: m[0] if m[0].startswith('"') else " ", text)
    text = re.sub(
        r'("(?:[^"\\]|\\.)*")|,(\s*[}\]])', lambda m: m[1] if m[1] is not None else m[2], text
    )
    return json.loads(text)


def migrate(root, args, previous):
    sources = installations(root)
    if not sources:
        raise ValueError("No installer integration found to migrate")
    if any(getattr(args, name) is not None for name in ("remote", "branch", "db", "corpora")):
        raise ValueError("Migration preserves settings; edit policy/settings after adoption")
    if previous and "migration" not in previous:
        raise ValueError(
            "Package settings already exist; resolve them before adopting an installer"
        )
    selected = sources[0]
    states = {
        name: json.loads(local_path(root, name + "/install.json").read_bytes()) for name in sources
    }
    for state in states.values():
        if state.get("format") != "repo-search-install-v1":
            raise ValueError("Unsupported installer metadata; inspect it before migrating")
    settings = json.loads(local_path(root, selected + "/runtime.json").read_bytes())
    settings.setdefault("remote", "origin")
    settings.setdefault("branch", "main")
    settings.setdefault("profile", ".opencode/search/profiles.json")
    settings.setdefault("policy_source", "upstream")
    profile_path = local_path(root, settings["profile"])
    profile = json.loads(profile_path.read_bytes())
    validate_profile(profile)
    # Do not pin local policy, fetch, start a daemon or provision Python during a preview.
    MainSource.discover(
        root, remote=settings["remote"], branch=settings["branch"], profile=settings["profile"]
    )
    if settings["policy_source"] not in {"local", "upstream"}:
        raise ValueError("Unsupported policy source")
    if args.action == "git-commit" and settings["policy_source"] == "local":
        raise ValueError(
            "Private policy must be made shared through the installer before "
            "git-commit migration; git-ignore migration preserves its index identity"
        )
    servers = {}
    for state in states.values():
        for name in state.get("servers", []):
            servers.setdefault(name, []).append(state.get("server_config", {}).get(name))
    for name in (
        "opencode.json",
        "opencode.jsonc",
        ".opencode/opencode.json",
        ".opencode/opencode.jsonc",
    ):
        path = local_path(root, name)
        if not path.exists():
            continue
        configured = jsonc(path).get("mcp", {}).get("servers", {})
        for server, expected in servers.items():
            if server in configured and configured[server] not in expected:
                raise ValueError(
                    f"MCP {server} was customized in {name}; reconcile it before migration"
                )
    migration = {
        "sources": sources,
        "servers": sorted(servers),
        "legacy_hooks": local_path(root, ".opencode/plugins/repo-search.js").is_file(),
    }
    replacements = {}
    loader = local_path(root, LOADER)
    if ".opencode/search-local" in sources and loader.exists():
        raw = loader.read_bytes()
        expected = states[".opencode/search-local"].get("files", {}).get(LOADER)
        adopted = previous.get("migration", {}).get("sources") == sources and raw == STUB
        if not adopted and hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Customized private loader: {LOADER}; reconcile it before migration")
        replacements[LOADER] = STUB
    # Config-file commands and skills are keyed by name/ID, and package transforms
    # override those entries. Preserve customized content by refusing to shadow it.
    for state in states.values():
        for name, expected in state.get("files", {}).items():
            if name.startswith(
                (".opencode/commands/search-", ".claude/skills/repo-knowledge-search/")
            ) or name in {
                ".opencode/search-local/private-plugin.js",
                ".opencode/search-local/registration.js",
                ".opencode/search-local/guidance/SKILL.md",
            }:
                path = local_path(root, name)
                if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != expected:
                    raise ValueError(
                        f"Customized search guidance: {name}; reconcile it before migration"
                    )
    settings_name = str(DIRECTORY / "runtime.json")
    if previous and local_path(root, settings_name).read_bytes() != encoded(settings):
        raise ValueError(
            "Adopted package settings differ from the installer; keep the current "
            "package settings or reconcile them before repeating migration"
        )
    files = {settings_name: encoded(settings), **replacements}
    if args.action == "git-ignore":
        tracked = git(
            root,
            "ls-files",
            "--",
            *[":(literal)" + n for n in [*files, str(DIRECTORY / "install.json")]],
        ).stdout
        if tracked:
            raise ValueError("Migration metadata/loader is tracked; use git-commit migration")
    state = {
        "format": "repo-search-install-v1",
        "layout": "package",
        "visibility": previous.get("visibility", "undecided"),
        "migration": migration,
        "files": {name: hashlib.sha256(raw).hexdigest() for name, raw in files.items()},
    }
    result = {
        "migration": migration,
        "directory": str(root / DIRECTORY),
        "profile": settings["profile"],
        "policy_source": settings["policy_source"],
        "settings": settings,
        "files": list(files),
        "dry_run": args.dry_run,
        "visibility": previous.get("visibility", states[selected].get("visibility", "undecided")),
        "choices": ["git-ignore", "git-commit"]
        if settings["policy_source"] == "upstream"
        else ["git-ignore"],
        "inspection": inspect_repository(root, profile, settings),
    }
    if not args.action or args.dry_run:
        return result
    # Keep an immutable original private loader for recovery. Never remove copied
    # runtimes or customized policy; they remain usable by other clients.
    if replacements and loader.read_bytes() != STUB:
        common = Path(git(root, "rev-parse", "--git-common-dir").stdout.strip())
        raw = loader.read_bytes()
        backup = (
            (root / common).resolve() / "repo-search/migrations" / hashlib.sha256(raw).hexdigest()
        )
        if not backup.exists():
            write(backup, raw)
        result["loader_backup"] = str(backup)
    state_path = DIRECTORY / "install.json"
    pending = {**files, str(state_path): encoded(state)}
    originals = {
        name: local_path(root, name).read_bytes() if local_path(root, name).exists() else None
        for name in pending
    }
    try:
        for name, raw in pending.items():
            write(local_path(root, name), raw)
    except OSError:
        for name, raw in originals.items():
            path = local_path(root, name)
            if raw is None:
                path.unlink(missing_ok=True)
            else:
                write(path, raw)
        raise
    # Failed Git hooks leave the migration prepared, matching normal init actions.
    # Policy provenance and path remain identity inputs, independent of metadata visibility.
    applied = apply(root, root / DIRECTORY, args.action, message=args.message, preserve_policy=True)
    result.update(applied)
    result["next"] = (
        "Package registrations reload automatically; disconnect old MCPs and stop "
        "an incompatible installer daemon before the first package search"
    )
    return result

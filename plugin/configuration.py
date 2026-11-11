"""Resolve worktree and explicitly adopted repository-private package settings.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import fcntl
import hashlib
import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "payload/.opencode/search"))

from repo_search.installation import encoded, git  # noqa: E402
from repo_search.settings import validate_profile  # noqa: E402

DIRECTORY = Path(".opencode/search-package")
FORMAT = "repo-search-repository-config-v1"


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def locations(root):
    root = Path(git(root, "rev-parse", "--show-toplevel").stdout.strip()).resolve()
    common = Path(git(root, "rev-parse", "--git-common-dir").stdout.strip())
    return root, (root / common).resolve()


def repository_path(common):
    path = common / "repo-search/package.json"
    if path.is_symlink() or not path.resolve().is_relative_to(common):
        raise ValueError("Repository search configuration must stay in the Git common directory")
    return path


def local_path(root, name):
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or ".git" in path.parts:
        raise ValueError("Package profile must be a repository-relative path")
    target = root / path
    if not target.resolve().is_relative_to(root):
        raise ValueError("Package settings resolve outside the worktree")
    return target


def optional(path):
    return json.loads(path.read_bytes()) if path.is_file() else None


def local_binding(root, config):
    return {
        "runtime": digest((root / DIRECTORY / "runtime.json").read_bytes()),
        "profile": digest(local_path(root, config["profile"]).read_bytes()),
    }


def resolve(root):
    """Select a complete configuration; discovery never writes, pins or fetches."""
    root, common = locations(root)
    shared_path = repository_path(common)
    shared = optional(shared_path)
    if shared_path.is_file() and (not isinstance(shared, dict) or shared.get("format") != FORMAT):
        raise ValueError("Unsupported repository-private search configuration")
    path = root / DIRECTORY / "runtime.json"
    tracked = bool(
        git(root, "ls-files", "--", ":(literal)" + str(DIRECTORY / "runtime.json")).stdout
    )
    config = optional(path) if path.is_file() and (not tracked or shared is None) else None
    if (
        path.is_file()
        and (not tracked or shared is None)
        and (not isinstance(config, dict) or not isinstance(config.get("profile"), str))
    ):
        raise ValueError("Invalid worktree search settings")
    adopted = shared and shared.get("adoptions", {}).get(str(root))
    if config and adopted and local_binding(root, config) == adopted:
        config = None
    if config is not None:
        profile = json.loads(local_path(root, config["profile"]).read_bytes())
        state = optional(root / DIRECTORY / "install.json") or {}
        source, scope = ("committed" if tracked else "worktree-private"), "worktree"
        origin = root
    elif shared is not None:
        config, profile = shared["settings"], shared["profile"]
        if not isinstance(config, dict) or not isinstance(config.get("profile"), str):
            raise ValueError("Invalid repository search settings")
        state = shared.get("installation", {})
        source, scope, path = "repository-private", "repository", shared_path
        origin = Path(shared["origin_worktree"])
    else:
        config = profile = None
        state = {}
        source, scope, path, origin = "none", None, None, root
    if config is not None:
        if not isinstance(config, dict) or not isinstance(config.get("profile"), str):
            raise ValueError("Invalid repository search settings")
        local_path(root, config["profile"])
        validate_profile(profile)
    return {
        "root": str(root),
        "common_dir": str(common),
        "source": source,
        "scope": scope,
        "inherited": source == "repository-private" and root != origin,
        "path": str(path) if path else None,
        "settings": config,
        "profile": profile,
        "installation": state,
    }


def provenance(configuration):
    return {
        name: configuration[name]
        for name in ("root", "common_dir", "source", "scope", "inherited", "path")
    }


@contextmanager
def repository_lock(common):
    path = repository_path(common)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix(".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield path


def publish(path, document):
    """One replace publishes settings, profile and ownership metadata together."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encoded(document))
        temporary.replace(path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)

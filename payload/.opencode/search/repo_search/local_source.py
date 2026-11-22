"""Read committed local revisions without following later checkout switches.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from repo_search.git_source import read_tree


def local_environment() -> dict:
    """Partial clones must report missing objects, not lazily fetch during preview."""
    return {**os.environ, "GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"}


def command(root: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=False,
        env=local_environment(),
    )


def resolve_commit(root: Path, ref: str) -> str:
    result = command(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
    if result.returncode:
        raise ValueError("Bound local branch or commit is unavailable")
    return result.stdout.strip()


@dataclass(frozen=True)
class LocalGitSnapshot:
    """Exact source object IDs; no bytes come from the mutable checkout or index."""

    root: Path
    ref: str
    commit: str
    tree: str
    blobs: dict[str, str]


@dataclass(frozen=True)
class LocalRevision:
    """A local branch binding or detached full commit, independent of current HEAD."""

    root: Path
    ref: str

    @classmethod
    def bind(cls, root: Path, ref: str = "HEAD") -> LocalRevision:
        location = command(root, "rev-parse", "--show-toplevel")
        if location.returncode:
            raise ValueError("Local source must be inside a Git worktree")
        root = Path(location.stdout.strip()).resolve()
        if not isinstance(ref, str) or not ref or ref.startswith("-"):
            raise ValueError("Select HEAD, a local branch or a full commit ID")
        if ref == "HEAD":
            symbolic = command(root, "symbolic-ref", "--quiet", "HEAD")
            if symbolic.returncode == 0:
                ref = symbolic.stdout.strip()
            elif symbolic.returncode == 1:
                ref = resolve_commit(root, "HEAD")
            else:
                raise ValueError("Cannot resolve local HEAD")
        full_commit = re.fullmatch(r"[a-fA-F0-9]{40}|[a-fA-F0-9]{64}", ref)
        if full_commit:
            kind = command(root, "cat-file", "-t", ref)
            if kind.returncode or kind.stdout.strip() != "commit":
                raise ValueError("Full object ID must identify a commit")
            ref = resolve_commit(root, ref)
        else:
            if ref.startswith("refs/") and not ref.startswith("refs/heads/"):
                raise ValueError("Only local branch refs are supported")
            ref = ref if ref.startswith("refs/heads/") else "refs/heads/" + ref
            if command(root, "check-ref-format", ref).returncode:
                raise ValueError("Invalid local branch ref")
            resolve_commit(root, ref)
        return cls(root, ref)

    def snapshot(self) -> LocalGitSnapshot:
        """Resolve once, then enumerate only that committed tree without fetching."""
        commit = resolve_commit(self.root, self.ref)
        tree, blobs = read_tree(self.root, commit, env=local_environment())
        return LocalGitSnapshot(self.root, self.ref, commit, tree, blobs)

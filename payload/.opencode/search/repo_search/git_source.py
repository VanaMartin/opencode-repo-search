"""Read one immutable upstream-branch snapshot without touching checkout files.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from repo_search.chunks import sha256
from repo_search.settings import validate_profile

PROFILE = ".opencode/search/profiles.json"


def policy_store(root: Path) -> Path:
    common = Path(git(root, "rev-parse", "--git-common-dir").decode().strip())
    return (root / common).resolve() / "repo-search/policies"


def pin_policy(root: Path, path: str) -> str:
    profile = json.loads((root / path).read_bytes())
    validate_profile(profile)
    raw = (json.dumps(profile, sort_keys=True, ensure_ascii=False) + "\n").encode()
    digest = hashlib.sha256(raw).hexdigest()
    store = policy_store(root)
    store.mkdir(parents=True, exist_ok=True)
    destination = store / (digest + ".json")
    with tempfile.NamedTemporaryFile(dir=store, delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(raw)
    temporary.replace(destination)
    return digest


def git(root: Path, *args: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(root), *args])


def repository_id(url: str, root: Path) -> str:
    """Share SSH/HTTPS mounts of one upstream, without retaining credentials."""
    scp = re.fullmatch(r"(?:[^/@:]+@)?([^/:]+):(.+)", url)
    if "://" not in url and scp:
        host, path = scp.groups()
        host = host.lower()
    elif "://" in url:
        parts = urlsplit(url)
        if parts.scheme == "file":
            if parts.hostname not in {None, "localhost"}:
                raise ValueError("File upstream must be local")
            return "file:" + str(Path(unquote(parts.path)).resolve())
        host = (parts.hostname or "").lower()
        if not host or parts.scheme not in {"ssh", "https", "http", "git"}:
            raise ValueError("Unsupported upstream URL")
        port = parts.port
        default_port = {"ssh": 22, "https": 443, "http": 80, "git": 9418}[parts.scheme]
        if port and port != default_port:
            host += f":{port}"
        path = parts.path
    else:
        return "file:" + str((root / url).resolve())
    path = path.strip("/").removesuffix(".git")
    if host == "github.com":
        path = path.lower()
    return f"{host}/{path}"


def read_blobs(root: Path, oids: list[str]) -> dict[str, bytes]:
    """Batch object reads; paths, filters, and dirty files never supply source bytes."""
    if not oids:
        return {}
    data = subprocess.check_output(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input="".join(oid + "\n" for oid in oids).encode(),
    )
    result = {}
    offset = 0
    for expected in oids:
        end = data.index(b"\n", offset)
        oid, kind, length = data[offset:end].split()
        if oid.decode() != expected or kind != b"blob":
            raise ValueError("Unexpected Git object in source snapshot")
        length = int(length)
        result[expected] = data[end + 1 : end + 1 + length]
        offset = end + length + 2
    return result


@dataclass(frozen=True)
class MainSource:
    root: Path
    remote: str
    profile_path: str
    repo_id: str
    corpus: str = "repository"
    branch: str = "main"
    policy_hash: str | None = None

    @classmethod
    def discover(
        cls,
        root: Path,
        remote: str = "origin",
        profile: str = PROFILE,
        *,
        corpus: str = "repository",
        branch: str = "main",
        policy_source: str = "upstream",
        policy_hash: str | None = None,
    ) -> MainSource:
        root = Path(git(root, "rev-parse", "--show-toplevel").decode().strip()).resolve()
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", remote):
            raise ValueError("Remote must be a configured Git remote name")
        path = Path(profile)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Profile must be a repository-relative path")
        if policy_source not in {"upstream", "local"}:
            raise ValueError("Policy source must be upstream or local")
        if policy_hash is not None:
            if not re.fullmatch(r"[a-f0-9]{64}", policy_hash):
                raise ValueError("Invalid local policy hash")
        elif policy_source == "local":
            policy_hash = pin_policy(root, path.as_posix())
        if not re.fullmatch(r"[a-z][a-z0-9_]*", corpus):
            raise ValueError("Corpus must be a lowercase identifier")
        subprocess.run(
            ["git", "check-ref-format", "refs/heads/" + branch], check=True, capture_output=True
        )
        url = git(root, "remote", "get-url", remote).decode().strip()
        return cls(
            root, remote, path.as_posix(), repository_id(url, root), corpus, branch, policy_hash
        )

    @property
    def owner(self) -> dict:
        owner = {
            "repo_id": self.repo_id,
            "branch": self.branch,
            "profile_path": self.profile_path,
            "corpus": self.corpus,
        }
        if self.policy_hash:
            owner["policy_sha256"] = self.policy_hash
        return owner

    @property
    def table(self) -> str:
        key = json.dumps(self.owner, sort_keys=True)
        return f"repo_{self.corpus}_{sha256(key)[:16]}"

    @property
    def ref(self) -> str:
        return f"refs/remotes/{self.remote}/{self.branch}"

    def fetch(self) -> Snapshot:
        url = git(self.root, "remote", "get-url", self.remote).decode().strip()
        if repository_id(url, self.root) != self.repo_id:
            raise ValueError("Configured upstream changed since mount")
        env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
        env.setdefault("GIT_SSH_COMMAND", "ssh -oBatchMode=yes -oConnectTimeout=10")
        result = subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "fetch",
                "--no-tags",
                self.remote,
                f"+refs/heads/{self.branch}:{self.ref}",
            ],
            env=env,
            capture_output=True,
            timeout=60,
        )
        if result.returncode:
            # Git errors may contain credential-bearing URLs. Keep those on the
            # Git side of the boundary instead of returning them through MCP.
            raise RuntimeError(
                f"Cannot fetch {self.remote}/{self.branch} (Git exit {result.returncode})"
            )
        url = git(self.root, "remote", "get-url", self.remote).decode().strip()
        if repository_id(url, self.root) != self.repo_id:
            raise ValueError("Configured upstream changed during fetch")
        commit = git(self.root, "rev-parse", f"{self.ref}^{{commit}}").decode().strip()
        tree = git(self.root, "rev-parse", f"{commit}^{{tree}}").decode().strip()
        blobs = {}
        for entry in git(self.root, "ls-tree", "-r", "-z", commit).split(b"\0"):
            if not entry:
                continue
            metadata, path = entry.split(b"\t", 1)
            mode, kind, oid = metadata.split()
            if kind == b"blob" and mode in {b"100644", b"100755"}:
                blobs[path.decode("utf-8")] = oid.decode()
        if self.policy_hash:
            policy = (policy_store(self.root) / (self.policy_hash + ".json")).read_bytes()
            if hashlib.sha256(policy).hexdigest() != self.policy_hash:
                raise ValueError("Local policy snapshot does not match its hash")
        else:
            if self.profile_path not in blobs:
                raise ValueError(
                    "Indexing profile is absent from the fetched branch; "
                    "publish it or use a local policy"
                )
            policy = read_blobs(self.root, [blobs[self.profile_path]])[blobs[self.profile_path]]
        profile = json.loads(policy)
        validate_profile(profile)
        if self.corpus not in profile["corpora"]:
            raise ValueError(f"Corpus {self.corpus} is absent from the committed profile")
        provenance = {
            "source": "local" if self.policy_hash else "upstream",
            "path": self.profile_path,
            "sha256": hashlib.sha256(policy).hexdigest(),
        }
        return Snapshot(self, commit, tree, blobs, profile, provenance)


@dataclass(frozen=True)
class Snapshot:
    source: MainSource
    commit: str
    tree: str
    blobs: dict[str, str]
    profile: dict
    provenance: dict

    @property
    def policy(self) -> dict:
        return self.profile["corpora"][self.source.corpus]

    def selected(self) -> dict[str, str]:
        policy = self.policy
        extensions = policy["extensions"]
        excluded = policy["exclude"]

        def matches(path, patterns):
            return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)

        return {
            path: oid
            for path, oid in sorted(self.blobs.items())
            if matches(path, policy["include"])
            and not matches(path, excluded)
            and (
                Path(path).suffix in extensions
                or matches(path, policy.get("extensionless_files", []))
            )
        }

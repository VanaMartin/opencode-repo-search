"""Worktree-owned local collection metadata; never provision or maintain an index.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

from __future__ import annotations

import copy
import fcntl
import fnmatch
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from repo_search.articles import paper_metadata
from repo_search.git_source import read_blobs
from repo_search.local_source import LocalRevision, command, local_environment, resolve_commit
from repo_search.settings import validate_profile

FORMAT = "repo-search-local-registry-v1"
POLICY_FIELDS = {
    "description",
    "parser",
    "source_kind",
    "include",
    "exclude",
    "extensions",
    "extensionless_files",
}
EMBEDDING_FIELDS = {
    "registry",
    "model",
    "device",
    "dimensions",
    "chunk_target_tokens",
    "chunk_max_tokens",
    "total_input_max_tokens",
    "overlap_tokens",
}


def encoded(value) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode()


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("Duplicate local registry JSON key")
        result[name] = value
    return result


def identifier(value) -> bool:
    return (
        isinstance(value, str)
        and re.fullmatch(r"[a-f0-9]{32}", value) is not None
        and uuid.UUID(value).version == 4
    )


def validate_name(name):
    if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name):
        raise ValueError("Local collection names need 1–64 lowercase letters, digits, _ or -")


def validate_local_profile(profile):
    try:
        if not isinstance(profile, dict) or set(profile) != {"format", "embedding", "corpora"}:
            raise ValueError("Local policy needs a standalone profile")
        embedding = profile["embedding"]
        if not isinstance(embedding, dict) or set(embedding) != EMBEDDING_FIELDS:
            raise ValueError("Invalid local embedding configuration")
        if not isinstance(embedding["model"], str) or not embedding["model"].strip():
            raise ValueError("Set a local embedding model")
        for name in EMBEDDING_FIELDS - {"registry", "model", "device"}:
            if type(embedding[name]) is not int:
                raise ValueError("Local embedding budgets and dimensions must be integers")
        if not isinstance(profile["corpora"], dict) or set(profile["corpora"]) != {"local"}:
            raise ValueError("Local policy must define exactly one local corpus")
        policy = profile["corpora"]["local"]
        if not isinstance(policy, dict) or policy.keys() - POLICY_FIELDS - {"server", "enabled"}:
            raise ValueError("Unsupported local policy fields")
        if policy.get("server") != "lancedb-local" or policy.get("enabled") is not True:
            raise ValueError("Local policy requires its reserved read-only MCP identity")
        validate_profile(profile)
        for name in ("description", "source_kind"):
            if name in policy and not isinstance(policy[name], str):
                raise ValueError(f"Local {name} must be a string")
        for name in ("include", "exclude", "extensionless_files"):
            patterns = policy.get(name, [])
            if not isinstance(patterns, list) or not all(isinstance(p, str) for p in patterns):
                raise ValueError(f"Local {name} must be a list of patterns")
            if any(
                not p
                or "\0" in p
                or Path(p).is_absolute()
                or ".." in Path(p).parts
                or ".git" in Path(p).parts
                or "\\" in p
                or re.match(r"^[A-Za-z]:", p)
                for p in patterns
            ):
                raise ValueError("Local patterns must stay within the repository")
        for extension in policy["extensions"]:
            if not re.fullmatch(r"\.[A-Za-z0-9_+-]+", extension) or extension.lower() in {
                ".pdf",
                ".docx",
                ".pptx",
                ".xlsx",
                ".png",
                ".jpg",
                ".jpeg",
                ".npy",
                ".npz",
            }:
                raise ValueError("Select UTF-8 text extensions, not binary output")
    except (KeyError, TypeError, AttributeError) as error:
        raise ValueError("Invalid standalone local policy") from error


def make_profile(embedding: dict, policy: dict) -> dict:
    if not isinstance(policy, dict) or policy.keys() - POLICY_FIELDS:
        raise ValueError("Supply local selection/parser fields, not normal corpus identities")
    profile = {
        "format": "repo-search-profiles-v1",
        "embedding": copy.deepcopy(embedding),
        "corpora": {"local": {**copy.deepcopy(policy), "enabled": True, "server": "lancedb-local"}},
    }
    validate_local_profile(profile)
    return profile


def database_path(common: Path, explicit: Path | None = None) -> Path:
    if explicit is not None:
        path = Path(explicit).expanduser()
        if not path.is_absolute():
            raise ValueError("Local database must be an explicit absolute path")
        return path.resolve()
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    identity = digest(str(common).encode())[:20]
    return (base / "repo-search" / ("local-" + identity) / "lancedb").expanduser().resolve()


def inspect_selection(snapshot, profile):
    policy = profile["corpora"]["local"]

    def matches(path, patterns):
        return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)

    included = [path for path in snapshot.blobs if matches(path, policy["include"])]
    excluded = {path for path in included if matches(path, policy["exclude"])}
    paths = sorted(
        path
        for path in included
        if path not in excluded
        and (
            Path(path).suffix in policy["extensions"]
            or matches(path, policy.get("extensionless_files", []))
        )
    )
    errors, size, papers = [], 0, set()
    # Bound temporary blob materialization; no tokenizer/model is needed for preview.
    for start in range(0, len(paths), 64):
        group = paths[start : start + 64]
        try:
            blobs = read_blobs(
                snapshot.root,
                list(dict.fromkeys(snapshot.blobs[p] for p in group)),
                env=local_environment(),
            )
        except (ValueError, subprocess.CalledProcessError) as error:
            raise ValueError(
                "Selected local Git blobs are unavailable; restore missing Git objects explicitly"
            ) from error
        for path in group:
            raw = blobs[snapshot.blobs[path]]
            size += len(raw)
            try:
                text = raw.decode("utf-8")
                if "\0" in text:
                    raise ValueError("Binary NUL bytes are not supported")
                if policy["parser"] == "reference_note":
                    paper = paper_metadata(path, text)["paper_id"]
                    if paper in papers:
                        raise ValueError("Duplicate paper_id in this collection")
                    papers.add(paper)
            except (UnicodeError, ValueError) as error:
                errors.append({"path": path, "error": str(error)})
    if not paths:
        errors.append({"path": None, "error": "No committed text files selected"})
    return {
        "commit": snapshot.commit,
        "tree": snapshot.tree,
        "committed_files": len(snapshot.blobs),
        "included_files": len(included),
        "excluded_files": len(excluded),
        "unsupported_files": len(included) - len(excluded) - len(paths),
        "selected_files": len(paths),
        "selected_bytes": size,
        "sample_paths": paths[:5],
        "validation_errors": errors,
    }


@dataclass(frozen=True)
class LocalRegistry:
    root: Path
    git_dir: Path
    common_dir: Path

    @classmethod
    def discover(cls, root: Path) -> LocalRegistry:
        location = command(root, "rev-parse", "--show-toplevel")
        if location.returncode:
            raise ValueError("Local collections require a Git worktree")
        root = Path(location.stdout.strip()).resolve()
        directories = []
        for flag in ("--absolute-git-dir", "--git-common-dir"):
            result = command(root, "rev-parse", flag)
            if result.returncode:
                raise ValueError("Cannot resolve local collection Git metadata")
            directories.append((root / result.stdout.strip()).resolve())
        return cls(root, *directories)

    @property
    def directory(self) -> Path:
        return self.git_dir / "repo-search/local"

    @property
    def path(self) -> Path:
        return self.directory / "registry.json"

    @property
    def location(self) -> dict:
        return {name: str(getattr(self, name)) for name in ("root", "git_dir", "common_dir")}

    def check_paths(self):
        if self.discover(self.root) != self:
            raise ValueError("Local collection worktree/Git metadata location changed")
        current = self.git_dir
        if not current.is_dir() or current.resolve() != current:
            raise ValueError("Local Git metadata is unavailable or changed")
        for name in ("repo-search", "local"):
            current = current / name
            if current.is_symlink() or (current.exists() and not current.is_dir()):
                raise ValueError("Local collection metadata directories must not be symlinks")
        for path in (self.path, self.directory / "registry.lock"):
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ValueError("Local collection registry/lock must be regular files")

    def validate(self, document):
        if (
            not isinstance(document, dict)
            or set(document)
            != {
                "format",
                "location",
                "worktree_id",
                "collections",
            }
            or document["format"] != FORMAT
        ):
            raise ValueError("Unsupported local collection registry")
        if document["location"] != self.location or not identifier(document["worktree_id"]):
            raise ValueError("Local collection registry belongs to a different worktree")
        collections = document["collections"]
        if not isinstance(collections, dict):
            raise ValueError("Invalid local collection entries")
        identities = set()
        for name, entry in collections.items():
            validate_name(name)
            if not isinstance(entry, dict) or set(entry) != {
                "id",
                "ref",
                "created_commit",
                "profile",
                "policy_sha256",
                "database",
                "created_at",
                "state",
            }:
                raise ValueError("Invalid local collection entry")
            if not identifier(entry["id"]) or entry["id"] in identities:
                raise ValueError("Invalid or duplicate immutable local collection ID")
            identities.add(entry["id"])
            ref = entry["ref"]
            if not isinstance(ref, str) or not (
                re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", ref)
                or (
                    ref.startswith("refs/heads/")
                    and not command(self.root, "check-ref-format", ref).returncode
                )
            ):
                raise ValueError("Invalid bound local ref")
            if not isinstance(entry["created_commit"], str) or not re.fullmatch(
                r"[a-f0-9]{40}|[a-f0-9]{64}", entry["created_commit"]
            ):
                raise ValueError("Invalid local creation commit")
            validate_local_profile(entry["profile"])
            if digest(encoded(entry["profile"])) != entry["policy_sha256"]:
                raise ValueError("Local policy snapshot does not match its hash")
            database = entry["database"]
            if (
                not isinstance(database, str)
                or str(database_path(self.common_dir, Path(database))) != database
            ):
                raise ValueError("Local collection database path is not canonical")
            try:
                created = datetime.fromisoformat(entry["created_at"])
                if created.tzinfo is None:
                    raise ValueError("Missing timezone")
            except (TypeError, ValueError) as error:
                raise ValueError("Invalid local collection creation time") from error
            if entry["state"] != "registered":
                raise ValueError("Unsupported local collection lifecycle state")

    def read(self):
        self.check_paths()
        try:
            descriptor = os.open(self.path, os.O_RDONLY | os.O_NOFOLLOW)
        except FileNotFoundError:
            return None, digest(b"")
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Local collection registry must be a regular file")
            raw = stream.read()
        try:
            document = json.loads(raw, object_pairs_hook=unique_object)
        except (ValueError, UnicodeError) as error:
            raise ValueError("Invalid local collection registry JSON") from error
        self.validate(document)
        return document, digest(raw)

    def inspect(self) -> dict:
        document, revision = self.read()
        return {
            **self.location,
            "revision": revision,
            "worktree_id": document["worktree_id"] if document else None,
            "collections": [
                self.details(name, document) for name in sorted(document["collections"])
            ]
            if document
            else [],
        }

    def details(self, name, document):
        entry = copy.deepcopy(document["collections"][name])
        return {
            **entry,
            "name": name,
            "worktree_id": document["worktree_id"],
            "table": "local_" + entry["id"],
            "experimental": True,
            "publication": {"state": "not_checked"},
        }

    def status(self, name: str) -> dict:
        validate_name(name)
        document, _ = self.read()
        if document is None or name not in document["collections"]:
            raise ValueError("Unknown local collection in this worktree")
        result = self.details(name, document)
        try:
            result["source"] = {
                "state": "available",
                "commit": resolve_commit(self.root, result["ref"]),
            }
        except ValueError as error:
            result["source"] = {"state": "unavailable", "error": str(error)}
        return result

    def preview(
        self, name: str, profile: dict, *, ref="HEAD", database=None, context_revision=None
    ):
        validate_name(name)
        validate_local_profile(profile)
        if context_revision is not None and (
            not isinstance(context_revision, str)
            or not re.fullmatch(r"[a-f0-9]{64}", context_revision)
        ):
            raise ValueError("Invalid local creation configuration revision")
        document, base_revision = self.read()
        if document and name in document["collections"]:
            raise ValueError("Local collection already exists in this worktree")
        snapshot = LocalRevision.bind(self.root, ref).snapshot()
        selected_database = database_path(self.common_dir, database)
        inspection = inspect_selection(snapshot, profile)
        proposal = {
            "location": self.location,
            "name": name,
            "ref": snapshot.ref,
            "profile": copy.deepcopy(profile),
            "database": str(selected_database),
            "inspection": inspection,
            "base_revision": base_revision,
            "context_revision": context_revision,
        }
        return {
            **proposal,
            "revision": digest(encoded(proposal)),
            "applied": False,
            "policy_sha256": digest(encoded(profile)),
            "worktree_id": document["worktree_id"] if document else None,
        }

    @contextmanager
    def lock(self):
        self.check_paths()
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.check_paths()
        descriptor = os.open(
            self.directory / "registry.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(descriptor, "a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            self.check_paths()
            if os.fstat(stream.fileno()).st_ino != (self.directory / "registry.lock").stat().st_ino:
                raise ValueError("Local collection registry lock changed during creation")
            yield

    def publish(self, document):
        self.validate(document)
        self.check_paths()
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.directory, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(encoded(document))
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)

    def create(
        self, name: str, profile: dict, *, expect_revision: str, context_check=None, **options
    ) -> dict:
        if not isinstance(expect_revision, str) or not re.fullmatch(
            r"[a-f0-9]{64}", expect_revision
        ):
            raise ValueError("Creation requires the revision from a reviewed local preview")
        # Reject invalid/stale requests before creating any metadata directories.
        preview = self.preview(name, profile, **options)
        if preview["revision"] != expect_revision:
            raise ValueError("Local source, policy, database or registry changed since preview")
        if preview["inspection"]["validation_errors"]:
            raise ValueError("Local source selection is invalid; inspect preview validation_errors")
        with self.lock():
            if context_check and context_check() != options.get("context_revision"):
                raise ValueError("Local creation configuration changed since preview")
            preview = self.preview(name, profile, **options)
            if preview["revision"] != expect_revision:
                raise ValueError("Local source, policy, database or registry changed since preview")
            document, _ = self.read()
            if document is None:
                document = {
                    "format": FORMAT,
                    "location": self.location,
                    "worktree_id": uuid.uuid4().hex,
                    "collections": {},
                }
            document["collections"][name] = {
                "id": uuid.uuid4().hex,
                "ref": preview["ref"],
                "created_commit": preview["inspection"]["commit"],
                "profile": preview["profile"],
                "policy_sha256": preview["policy_sha256"],
                "database": preview["database"],
                "created_at": datetime.now(UTC).isoformat(),
                "state": "registered",
            }
            self.publish(document)
        return {"applied": True, "collection": self.details(name, document)}

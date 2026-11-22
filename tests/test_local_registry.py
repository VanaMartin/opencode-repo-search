"""Private collection registries, immutable policy capture and explicit creation.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import copy
import json
import os
import shlex
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from repo_search.local_registry import LocalRegistry, make_profile
from test_local_source import commit, git
from test_local_source import local_repo as local_repo

BUNDLE = Path(__file__).resolve().parents[1]
DEFAULT = json.loads((BUNDLE / "payload/.opencode/search/profiles.json").read_bytes())


@pytest.fixture
def profile():
    return make_profile(
        DEFAULT["embedding"],
        {
            "parser": "source",
            "include": ["*.py"],
            "exclude": [],
            "extensions": [".py"],
        },
    )


def create(registry, profile, name="co-experiment", **options):
    preview = registry.preview(name, profile, **options)
    return registry.create(name, profile, expect_revision=preview["revision"], **options)[
        "collection"
    ]


def test_discovery_preview_and_missing_status_create_nothing(
    local_repo, profile, tmp_path, monkeypatch
):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    registry = LocalRegistry.discover(local_repo)
    before = git(local_repo, "status", "--porcelain=v1"), git(local_repo, "show-ref")
    assert registry.inspect()["collections"] == []
    assert registry.inspect()["worktree_id"] is None
    with pytest.raises(ValueError, match="Unknown local"):
        registry.status("missing")
    preview = registry.preview("co-experiment", profile)
    assert not preview["applied"] and preview["worktree_id"] is None
    assert preview["inspection"]["selected_files"] == 1
    assert preview["inspection"]["selected_bytes"] == len("value = 'experiment'\n")
    assert preview["ref"] == "refs/heads/experiment"
    assert not (registry.git_dir / "repo-search").exists()
    assert not (tmp_path / "data").exists()
    assert before == (git(local_repo, "status", "--porcelain=v1"), git(local_repo, "show-ref"))


def test_creation_captures_independent_policy_and_persistent_identity(local_repo, profile):
    registry = LocalRegistry.discover(local_repo)
    original = copy.deepcopy(profile)
    entry = create(registry, profile)
    assert entry["experimental"] and entry["table"] == "local_" + entry["id"]
    assert entry["profile"] == original
    assert entry["state"] == "registered" and entry["publication"]["state"] == "not_checked"
    assert registry.directory.stat().st_mode & 0o777 == 0o700
    assert registry.path.stat().st_mode & 0o777 == 0o600
    assert (registry.directory / "registry.lock").stat().st_mode & 0o777 == 0o600
    profile["corpora"]["local"]["include"] = ["different/**"]
    reloaded = LocalRegistry.discover(local_repo)
    assert reloaded.status("co-experiment")["profile"] == original
    second = create(reloaded, original, "second")
    assert second["worktree_id"] == entry["worktree_id"] and second["id"] != entry["id"]
    assert len(registry.inspect()["collections"]) == 2
    before = registry.path.read_bytes()
    with pytest.raises(ValueError, match="already exists"):
        registry.preview("co-experiment", original)
    assert registry.path.read_bytes() == before


def test_linked_worktree_and_independent_projects_do_not_share_ownership(
    local_repo, profile, tmp_path
):
    registry = LocalRegistry.discover(local_repo)
    worker = tmp_path / "linked worker"
    git(local_repo, "worktree", "add", "-qb", "worker", str(worker), "main")
    linked = LocalRegistry.discover(worker)
    first = create(registry, profile)
    second = create(linked, profile)
    assert registry.git_dir != linked.git_dir and registry.common_dir == linked.common_dir
    assert first["database"] == second["database"]
    assert first["id"] != second["id"] and first["worktree_id"] != second["worktree_id"]
    assert first["ref"] == "refs/heads/experiment" and second["ref"] == "refs/heads/worker"
    foreign = tmp_path / "independent"
    subprocess.run(["git", "clone", "-q", str(local_repo), str(foreign)], check=True)
    third = create(LocalRegistry.discover(foreign), profile)
    assert third["database"] != first["database"] and third["id"] != first["id"]


def test_creation_does_not_change_normal_settings_git_or_existing_database(
    local_repo, profile, tmp_path
):
    root = local_repo
    settings = root / ".opencode/search-package"
    settings.mkdir(parents=True)
    files = {
        "profiles.json": b'{"normal": "unchanged"}',
        "runtime.json": b"settings",
        "install.json": b"ownership",
    }
    for name, raw in files.items():
        (settings / name).write_bytes(raw)
    database = tmp_path / "existing database"
    database.mkdir()
    marker = database / "normal-manifest.json"
    marker.write_text('{"generation": "normal"}')
    (root / "solver.py").write_text("staged = True\n")
    git(root, "add", "solver.py")
    (root / "solver.py").write_text("dirty = True\n")
    before = (
        git(root, "diff", "--cached"),
        git(root, "status", "--porcelain=v1"),
        git(root, "show-ref"),
    )
    entry = create(LocalRegistry.discover(root), profile, database=database)
    assert entry["database"] == str(database)
    assert {name: (settings / name).read_bytes() for name in files} == files
    assert marker.read_text() == '{"generation": "normal"}' and len(list(database.iterdir())) == 1
    assert before == (
        git(root, "diff", "--cached"),
        git(root, "status", "--porcelain=v1"),
        git(root, "show-ref"),
    )


@pytest.mark.parametrize(
    "change", ["branch", "commit", "policy", "database", "context", "registry"]
)
def test_stale_previews_are_rejected(local_repo, profile, tmp_path, change):
    registry = LocalRegistry.discover(local_repo)
    preview = registry.preview("co-experiment", profile)
    options = {}
    if change == "branch":
        git(local_repo, "switch", "-q", "main")
    elif change == "commit":
        (local_repo / "solver.py").write_text("advanced = True\n")
        commit(local_repo)
    elif change == "policy":
        profile["corpora"]["local"]["description"] = "Changed proposal"
    elif change == "database":
        options["database"] = tmp_path / "other database"
    elif change == "context":
        options["context_revision"] = "f" * 64
    else:
        create(registry, profile, "other")
    before = registry.path.read_bytes() if registry.path.exists() else None
    with pytest.raises(ValueError, match="changed since preview"):
        registry.create("co-experiment", profile, expect_revision=preview["revision"], **options)
    assert (registry.path.read_bytes() if registry.path.exists() else None) == before
    if before is None:
        assert not registry.directory.exists()


def test_concurrent_creations_serialize_and_cannot_overwrite(local_repo, profile):
    registry = LocalRegistry.discover(local_repo)
    plans = [registry.preview(name, profile) for name in ("first", "second")]

    def apply(plan):
        try:
            registry.create(plan["name"], profile, expect_revision=plan["revision"])
            return "created"
        except ValueError as error:
            assert "changed since preview" in str(error)
            return "stale"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(apply, plans)) == ["created", "stale"]
    assert len(registry.inspect()["collections"]) == 1


def test_process_writers_use_the_same_registry_lock(local_repo, profile):
    registry = LocalRegistry.discover(local_repo)
    plans = [registry.preview(name, profile) for name in ("first", "second")]
    script = """
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from repo_search.local_registry import LocalRegistry
plan = json.loads(sys.argv[3])
try:
    LocalRegistry.discover(Path(sys.argv[2])).create(
        plan['name'], plan['profile'], expect_revision=plan['revision'])
except ValueError as error:
    assert 'changed since preview' in str(error)
    sys.exit(1)
"""
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                "-S",
                "-c",
                script,
                str(BUNDLE / "payload/.opencode/search"),
                str(local_repo),
                json.dumps(plan),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for plan in plans
    ]
    try:
        outputs = [p.communicate(timeout=30) for p in processes]
        assert sorted(p.returncode for p in processes) == [0, 1], outputs
        assert len(registry.inspect()["collections"]) == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()


@pytest.mark.parametrize("name", ["", "../escape", "--flag", "Upper", "x/y", "a" * 65, "x\0y"])
def test_hostile_names_never_create_metadata(local_repo, profile, name):
    registry = LocalRegistry.discover(local_repo)
    with pytest.raises(ValueError):
        registry.preview(name, profile)
    assert not registry.directory.exists()


@pytest.mark.parametrize(
    "patch",
    [
        {"include": ["../escape/**"]},
        {"include": ["/escape/**"]},
        {"include": ["C:/escape"]},
        {"exclude": [".git/**"]},
        {"extensionless_files": "Dockerfile"},
        {"extensions": [".npz"]},
        {"table": "repo_repository"},
        {"server": "lancedb"},
    ],
)
def test_invalid_policy_fields_fail_closed(local_repo, profile, patch):
    registry = LocalRegistry.discover(local_repo)
    profile["corpora"]["local"].update(patch)
    with pytest.raises(ValueError):
        registry.preview("experiment", profile)
    assert not registry.directory.exists()


@pytest.mark.parametrize("content", [b"binary\0text", b"\xffnot utf8"])
def test_invalid_selected_text_can_be_previewed_but_not_created(local_repo, profile, content):
    (local_repo / "solver.py").write_bytes(content)
    commit(local_repo)
    registry = LocalRegistry.discover(local_repo)
    preview = registry.preview("experiment", profile)
    assert preview["inspection"]["validation_errors"][0]["path"] == "solver.py"
    with pytest.raises(ValueError, match="selection is invalid"):
        registry.create("experiment", profile, expect_revision=preview["revision"])
    assert not registry.directory.exists()


def test_selection_counts_exclusions_and_extensionless_text(local_repo, profile):
    for name, content in {
        "Dockerfile": "FROM scratch\n",
        "skip.py": "skip = True\n",
        "image.bin": "binary\0",
    }.items():
        (local_repo / name).write_text(content)
    commit(local_repo)
    policy = profile["corpora"]["local"]
    policy.update(include=["*"], exclude=["skip.py"], extensionless_files=["Dockerfile"])
    result = LocalRegistry.discover(local_repo).preview("experiment", profile)["inspection"]
    assert result["selected_files"] == 2 and result["excluded_files"] == 1
    assert result["unsupported_files"] == 2  # .gitignore and image.bin
    assert result["sample_paths"] == ["Dockerfile", "solver.py"]
    assert not result["validation_errors"]


def test_empty_selection_and_invalid_literature_notes_remain_unapplied(local_repo, profile):
    registry = LocalRegistry.discover(local_repo)
    profile["corpora"]["local"]["include"] = ["missing/**"]
    preview = registry.preview("empty", profile)
    assert "No committed" in preview["inspection"]["validation_errors"][0]["error"]
    (local_repo / "paper.md").write_text("# Inventory\nNo declarations.\n")
    commit(local_repo)
    profile["corpora"]["local"].update(
        parser="reference_note", include=["*.md"], extensions=[".md"]
    )
    preview = registry.preview("papers", profile)
    assert "Source" in preview["inspection"]["validation_errors"][0]["error"]
    with pytest.raises(ValueError, match="selection is invalid"):
        registry.create("papers", profile, expect_revision=preview["revision"])
    assert not registry.directory.exists()


@pytest.mark.parametrize(
    "field", ["format", "owner", "hash", "profile", "ref", "database", "table", "duplicate"]
)
def test_corrupted_or_wrong_owner_registry_is_never_overwritten(local_repo, profile, field):
    registry = LocalRegistry.discover(local_repo)
    create(registry, profile)
    document = json.loads(registry.path.read_bytes())
    entry = document["collections"]["co-experiment"]
    if field == "format":
        document["format"] = "unknown"
    elif field == "owner":
        document["location"]["root"] += "-other"
    elif field == "hash":
        entry["policy_sha256"] = "0" * 64
    elif field == "profile":
        entry["profile"] = []
    elif field == "ref":
        entry["ref"] = "HEAD~1"
    elif field == "database":
        entry["database"] = "relative"
    elif field == "table":
        entry["table"] = "repo_repository"
    else:
        document["collections"]["duplicate"] = copy.deepcopy(entry)
    raw = json.dumps(document).encode()
    registry.path.write_bytes(raw)
    for action in (registry.inspect, lambda: registry.preview("new", profile)):
        with pytest.raises(ValueError):
            action()
    assert registry.path.read_bytes() == raw


@pytest.mark.parametrize("target", ["repo-search", "local", "registry.json", "registry.lock"])
def test_metadata_symlinks_are_rejected_without_touching_target(
    local_repo, profile, tmp_path, target
):
    registry = LocalRegistry.discover(local_repo)
    outside = tmp_path / "outside"
    outside.mkdir()
    sentinel = outside / "sentinel"
    sentinel.write_bytes(b"preserve")
    path = {
        "repo-search": registry.git_dir / "repo-search",
        "local": registry.directory,
        "registry.json": registry.path,
        "registry.lock": registry.directory / "registry.lock",
    }[target]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(outside if target in {"repo-search", "local"} else sentinel)
    with pytest.raises(ValueError, match="symlink|regular"):
        registry.preview("experiment", profile)
    assert sentinel.read_bytes() == b"preserve" and list(outside.iterdir()) == [sentinel]


def test_failed_atomic_publication_keeps_last_registry(local_repo, profile, monkeypatch):
    registry = LocalRegistry.discover(local_repo)
    create(registry, profile)
    before = registry.path.read_bytes()
    preview = registry.preview("second", profile)
    original = Path.replace

    def fail(source, target):
        if target == registry.path:
            raise OSError("Publication interrupted")
        return original(source, target)

    monkeypatch.setattr(Path, "replace", fail)
    with pytest.raises(OSError, match="interrupted"):
        registry.create("second", profile, expect_revision=preview["revision"])
    assert registry.path.read_bytes() == before
    assert {p.name for p in registry.directory.iterdir()} == {"registry.json", "registry.lock"}


def test_deleted_branch_is_reported_without_retargeting_or_changing_registry(local_repo, profile):
    registry = LocalRegistry.discover(local_repo)
    entry = create(registry, profile)
    before = registry.path.read_bytes()
    git(local_repo, "switch", "-q", "main")
    assert registry.status("co-experiment")["source"]["commit"] == entry["created_commit"]
    git(local_repo, "branch", "-D", "experiment")
    assert registry.status("co-experiment")["source"]["state"] == "unavailable"
    assert registry.path.read_bytes() == before


def test_registry_import_and_preview_need_only_standard_library(local_repo, tmp_path):
    script = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from repo_search.local_registry import LocalRegistry
assert LocalRegistry.discover(Path(sys.argv[2])).inspect()['collections'] == []
assert 'torch' not in sys.modules and 'lancedb' not in sys.modules
"""
    subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            script,
            str(BUNDLE / "payload/.opencode/search"),
            str(local_repo),
        ],
        check=True,
    )
    assert not (local_repo / ".git/repo-search").exists()


def test_unborn_worktree_can_be_inspected_without_creating_identity(tmp_path, profile):
    git(tmp_path, "init", "-q", "--initial-branch=main")
    registry = LocalRegistry.discover(tmp_path)
    assert registry.inspect()["collections"] == []
    with pytest.raises(ValueError):
        registry.preview("experiment", profile)
    assert not registry.directory.exists()


def test_duplicate_json_keys_and_invalid_json_are_rejected(local_repo, profile):
    registry = LocalRegistry.discover(local_repo)
    create(registry, profile)
    raw = registry.path.read_bytes()
    for invalid in (b"not JSON", b"[]", b'{"format":"duplicate",' + raw.lstrip()[1:]):
        registry.path.write_bytes(invalid)
        with pytest.raises(ValueError):
            registry.inspect()
        assert registry.path.read_bytes() == invalid


def test_registry_copied_to_another_worktree_fails_closed(local_repo, profile, tmp_path):
    registry = LocalRegistry.discover(local_repo)
    create(registry, profile)
    worker = tmp_path / "worker"
    git(local_repo, "worktree", "add", "-qb", "worker", str(worker), "main")
    other = LocalRegistry.discover(worker)
    other.directory.mkdir(parents=True)
    other.path.write_bytes(registry.path.read_bytes())
    with pytest.raises(ValueError, match="different worktree"):
        other.inspect()


def test_partial_clone_preview_never_lazily_fetches_missing_blobs(local_repo, profile, tmp_path):
    git(local_repo, "config", "uploadpack.allowFilter", "true")
    partial = tmp_path / "partial"
    subprocess.run(
        [
            "git",
            "clone",
            "-q",
            "--no-checkout",
            "--filter=blob:none",
            local_repo.as_uri(),
            str(partial),
        ],
        check=True,
    )
    marker = tmp_path / "unexpected-fetch"
    trap = tmp_path / "fetch-trap.sh"
    trap.write_text("#!/bin/sh\ntouch " + shlex.quote(str(marker)) + "\nexit 99\n")
    trap.chmod(0o755)
    git(partial, "config", "remote.origin.uploadpack", shlex.quote(str(trap)))
    registry = LocalRegistry.discover(partial)
    with pytest.raises(ValueError, match="local Git blobs are unavailable"):
        registry.preview("experiment", profile)
    assert not marker.exists() and not registry.directory.exists()
    oid = git(local_repo, "rev-parse", "HEAD:solver.py")
    missing = subprocess.run(
        [
            "git",
            "-C",
            str(partial),
            "cat-file",
            "-e",
            oid,
        ],
        capture_output=True,
        env={**os.environ, "GIT_NO_LAZY_FETCH": "1"},
    )
    assert missing.returncode and not marker.exists()

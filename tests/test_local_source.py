"""Read isolated local branch snapshots without changing Git or upstream state.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import subprocess

import pytest
from repo_search.local_source import LocalRevision


def git(root, *arguments):
    return subprocess.check_output(["git", "-C", str(root), *arguments], text=True).strip()


def commit(root):
    git(root, "add", ".")
    git(root, "commit", "-qm", "Local fixture")
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def local_repo(tmp_path):
    root = tmp_path / "repository with spaces"
    root.mkdir()
    git(root, "init", "-q", "--initial-branch=main")
    git(root, "config", "user.name", "Local Search Test")
    git(root, "config", "user.email", "local@example.invalid")
    (root / "solver.py").write_text("value = 'main'\n")
    (root / ".gitignore").write_text("ignored.txt\n")
    commit(root)
    git(root, "switch", "-qc", "experiment")
    (root / "solver.py").write_text("value = 'experiment'\n")
    commit(root)
    return root


def test_snapshot_reads_committed_blobs_not_working_tree_or_index(local_repo):
    root = local_repo
    source = LocalRevision.bind(root)
    expected = git(root, "rev-parse", "HEAD")
    (root / "solver.py").write_text("value = 'staged'\n")
    git(root, "add", "solver.py")
    (root / "solver.py").write_text("value = 'dirty'\n")
    (root / "untracked.py").write_text("untracked = True\n")
    (root / "ignored.txt").write_text("ignored\n")
    before = git(root, "status", "--porcelain=v1"), git(root, "write-tree")
    snapshot = source.snapshot()
    assert snapshot.commit == expected
    assert snapshot.ref == "refs/heads/experiment"
    assert git(root, "cat-file", "blob", snapshot.blobs["solver.py"]) == "value = 'experiment'"
    assert "untracked.py" not in snapshot.blobs and "ignored.txt" not in snapshot.blobs
    assert before == (git(root, "status", "--porcelain=v1"), git(root, "write-tree"))
    assert not git(root, "remote")


def test_bound_branch_does_not_follow_checkout_switch_and_snapshots_stay_pinned(local_repo):
    root = local_repo
    source = LocalRevision.bind(root, "HEAD")
    original = source.snapshot()
    git(root, "switch", "-q", "main")
    assert source.snapshot().commit == original.commit
    git(root, "switch", "-q", "experiment")
    (root / "solver.py").write_text("value = 'advanced'\n")
    advanced = commit(root)
    assert source.snapshot().commit == advanced
    assert original.commit != advanced
    assert git(root, "cat-file", "blob", original.blobs["solver.py"]) == "value = 'experiment'"


def test_detached_head_binds_an_immutable_commit(local_repo):
    root = local_repo
    expected = git(root, "rev-parse", "HEAD")
    git(root, "checkout", "-q", "--detach", expected)
    source = LocalRevision.bind(root)
    assert source.ref == expected
    git(root, "switch", "-q", "main")
    assert source.snapshot().commit == expected
    assert LocalRevision.bind(root, expected).snapshot().commit == expected


@pytest.mark.parametrize("ref", ["experiment", "refs/heads/experiment"])
def test_explicit_local_branch_names(local_repo, ref):
    assert LocalRevision.bind(local_repo, ref).ref == "refs/heads/experiment"


@pytest.mark.parametrize(
    "ref",
    [
        "",
        "--help",
        "HEAD~1",
        "origin/main",
        "refs/remotes/origin/main",
        "refs/tags/main",
        "main:solver.py",
        "missing",
        "0" * 40,
    ],
)
def test_unsupported_or_missing_refs_fail_closed(local_repo, ref):
    with pytest.raises(ValueError):
        LocalRevision.bind(local_repo, ref)


def test_snapshot_excludes_symlinks_and_submodules(local_repo):
    root = local_repo
    (root / "linked.py").symlink_to("solver.py")
    git(root, "add", "linked.py")
    parent = git(root, "rev-parse", "HEAD")
    git(root, "update-index", "--add", "--cacheinfo", f"160000,{parent},submodule")
    git(root, "commit", "-qm", "Links fixture")
    assert git(root, "ls-tree", "HEAD", "linked.py").startswith("120000 blob ")
    assert git(root, "ls-tree", "HEAD", "submodule") == f"160000 commit {parent}\tsubmodule"
    snapshot = LocalRevision.bind(root).snapshot()
    assert "linked.py" not in snapshot.blobs and "submodule" not in snapshot.blobs
    assert "solver.py" in snapshot.blobs


def test_linked_worktree_binds_its_own_branch_without_retargeting_other_reader(
    local_repo, tmp_path
):
    root = local_repo
    worker = tmp_path / "linked worktree"
    git(root, "worktree", "add", "-qb", "second-experiment", str(worker), "main")
    first = LocalRevision.bind(root)
    second = LocalRevision.bind(worker)
    assert first.root == root.resolve() and second.root == worker.resolve()
    assert first.ref != second.ref
    assert first.snapshot().commit != second.snapshot().commit
    assert git(root, "branch", "--show-current") == "experiment"
    assert git(worker, "branch", "--show-current") == "second-experiment"


def test_deleted_binding_does_not_fall_back_to_current_branch(local_repo):
    source = LocalRevision.bind(local_repo)
    git(local_repo, "switch", "-q", "main")
    git(local_repo, "branch", "-D", "experiment")
    with pytest.raises(ValueError):
        source.snapshot()


@pytest.mark.parametrize("kind", ["blob", "tree", "tag"])
def test_full_object_ids_must_identify_commits_not_peelable_tags(local_repo, kind):
    root = local_repo
    if kind == "tag":
        git(root, "tag", "-am", "Local annotated tag", "local-tag")
        oid = git(root, "rev-parse", "refs/tags/local-tag")
    else:
        oid = git(root, "rev-parse", "HEAD:solver.py" if kind == "blob" else "HEAD^{tree}")
    with pytest.raises(ValueError):
        LocalRevision.bind(root, oid)


def test_unborn_repository_fails_without_creating_source_or_policy(tmp_path):
    git(tmp_path, "init", "-q", "--initial-branch=main")
    with pytest.raises(ValueError):
        LocalRevision.bind(tmp_path)
    assert not (tmp_path / ".git/repo-search").exists()


def test_regular_unicode_and_executable_paths_are_preserved(local_repo):
    root = local_repo
    (root / "résumé.py").write_text("value = 'unicode'\n")
    executable = root / "run experiment.sh"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o755)
    commit(root)
    snapshot = LocalRevision.bind(root).snapshot()
    assert {"résumé.py", "run experiment.sh"} <= snapshot.blobs.keys()
    assert not (root / ".git/repo-search").exists()

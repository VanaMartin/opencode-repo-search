"""Exercise channel promotion against disposable Git remotes, never production refs.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/promote_latest.py"
spec = importlib.util.spec_from_file_location("promote_latest", SCRIPT)
promotion = importlib.util.module_from_spec(spec)
spec.loader.exec_module(promotion)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def refs(root):
    return dict(line.split(" ", 1)[::-1] for line in git(root, "show-ref").splitlines())


def state(root):
    fetch_head = root / ".git/FETCH_HEAD"
    return (
        git(root, "rev-parse", "HEAD"),
        refs(root),
        git(root, "status", "--porcelain=v1"),
        git(root, "diff", "--cached"),
        git(root, "diff"),
        fetch_head.read_bytes() if fetch_head.exists() else None,
    )


@pytest.fixture
def release_repo(tmp_path):
    remote = tmp_path / "remote with spaces.git"
    root = tmp_path / "maintainer checkout"
    subprocess.run(
        ["git", "init", "--bare", "-q", "--initial-branch=main", str(remote)], check=True
    )
    subprocess.run(["git", "init", "-q", "--initial-branch=main", str(root)], check=True)
    for key, value in (
        ("user.name", "Release Test"),
        ("user.email", "release@example.invalid"),
        ("commit.gpgSign", "false"),
        ("tag.gpgSign", "false"),
    ):
        git(root, "config", key, value)
    git(root, "remote", "add", "origin", str(remote))
    (root / "README.md").write_text("Fixture source\n")
    commits = []
    for number in (1, 2):
        (root / "package.json").write_text(json.dumps({"version": f"0.1.0-rc.{number}"}))
        git(root, "add", ".")
        git(root, "commit", "-qm", f"candidate {number}")
        commits.append(git(root, "rev-parse", "HEAD"))
        git(root, "tag", "-a", f"v0.1.0-rc.{number}", "-m", f"candidate {number}")
    git(root, "push", "-q", "origin", "main", "--tags")
    return root, remote, commits


def invoke(root, candidate="v0.1.0-rc.2", *flags):
    return subprocess.run(
        [sys.executable, str(SCRIPT), candidate, "--repo", str(root), *flags],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_preview_push_and_repeat_preserve_local_work_and_unrelated_tags(release_repo):
    root, remote, commits = release_repo
    git(root, "tag", "-a", "latest", commits[0], "-m", "Old local channel")
    git(root, "tag", "-a", "do-not-publish", "-m", "Unpublished local tag")
    git(root, "config", "push.followTags", "true")
    git(root, "config", "fetch.pruneTags", "true")
    (root / "README.md").write_text("Staged user work\n")
    git(root, "add", "README.md")
    (root / "README.md").write_text("Dirty user work\n")
    (root / "untracked.txt").write_text("Untracked user work\n")
    (root / ".git/FETCH_HEAD").write_text("Preserve this fetch record\n")
    before, remote_before = state(root), refs(remote)

    preview = invoke(root)
    assert preview.returncode == 0, preview.stderr
    assert json.loads(preview.stdout)["state"] == "preview"
    assert refs(remote) == remote_before
    assert state(root) == before

    pushed = invoke(root, "v0.1.0-rc.2", "--push")
    assert pushed.returncode == 0, pushed.stderr
    assert json.loads(pushed.stdout)["state"] == "updated"
    assert refs(remote) == {**remote_before, "refs/tags/latest": commits[1]}
    assert state(root) == before

    repeated = invoke(root, "v0.1.0-rc.2", "--push")
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout)["state"] == "unchanged"
    assert refs(remote) == {**remote_before, "refs/tags/latest": commits[1]}
    assert state(root) == before


def test_existing_annotated_latest_moves_without_rewriting_local_tags(release_repo):
    root, remote, commits = release_repo
    git(root, "tag", "-a", "latest", commits[0], "-m", "Previous promotion")
    git(root, "push", "-q", "origin", "refs/tags/latest")
    before, remote_before = state(root), refs(remote)
    assert remote_before["refs/tags/latest"] != commits[0]
    result = invoke(root, "v0.1.0-rc.2", "--push")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["previous_latest"] == commits[0]
    assert refs(remote) == {**remote_before, "refs/tags/latest": commits[1]}
    assert state(root) == before


@pytest.mark.parametrize(
    "candidate", ["latest", "main", "v0.1.0", "v01.0.0-rc.2", "v0.1.0-rc.2^{}"]
)
def test_non_candidate_names_are_rejected(release_repo, candidate):
    root, remote, _ = release_repo
    before = refs(remote), state(root)
    result = invoke(root, candidate, "--push")
    assert result.returncode and "versioned candidate tag" in result.stderr
    assert (refs(remote), state(root)) == before


def test_missing_remote_candidate_is_rejected(release_repo):
    root, remote, _ = release_repo
    before = refs(remote), state(root)
    result = invoke(root, "v0.1.0-rc.99", "--push")
    assert result.returncode and "does not exist" in result.stderr
    assert (refs(remote), state(root)) == before


def test_tag_package_version_mismatch_is_rejected(release_repo):
    root, remote, _ = release_repo
    git(root, "tag", "-a", "v0.1.0-rc.3", "-m", "Incorrect candidate version")
    git(root, "push", "-q", "origin", "refs/tags/v0.1.0-rc.3")
    before = refs(remote), state(root)
    result = invoke(root, "v0.1.0-rc.3", "--push")
    assert result.returncode and "package.json version" in result.stderr
    assert (refs(remote), state(root)) == before


def test_remote_candidate_is_authoritative_not_a_divergent_local_tag(release_repo):
    root, remote, commits = release_repo
    git(root, "tag", "-f", "v0.1.0-rc.2", commits[0])
    before = state(root)
    result = invoke(root, "v0.1.0-rc.2", "--push")
    assert result.returncode == 0, result.stderr
    assert refs(remote)["refs/tags/latest"] == commits[1]
    assert state(root) == before


def test_missing_local_candidate_object_is_fetched_without_local_ref_changes(
    release_repo, tmp_path
):
    _, remote, commits = release_repo
    root = tmp_path / "tagless checkout"
    subprocess.run(
        ["git", "clone", "-q", "--no-local", "--no-tags", str(remote), str(root)], check=True
    )
    assert not git(root, "tag")
    tag_object = refs(remote)["refs/tags/v0.1.0-rc.2"]
    assert subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", tag_object], capture_output=True
    ).returncode
    before = state(root)
    result = invoke(root, "v0.1.0-rc.2", "--push")
    assert result.returncode == 0, result.stderr
    assert refs(remote)["refs/tags/latest"] == commits[1]
    assert state(root) == before


def test_separate_push_url_is_used_for_reads_and_writes(release_repo, tmp_path):
    root, remote, commits = release_repo
    git(root, "remote", "set-url", "--push", "origin", str(remote))
    git(root, "remote", "set-url", "origin", str(tmp_path / "not-the-push-remote.git"))
    result = invoke(root, "v0.1.0-rc.2", "--push")
    assert result.returncode == 0, result.stderr
    assert refs(remote)["refs/tags/latest"] == commits[1]


def test_multiple_push_destinations_are_rejected(release_repo, tmp_path):
    root, remote, _ = release_repo
    git(root, "config", "--add", "remote.origin.pushurl", str(remote))
    git(root, "config", "--add", "remote.origin.pushurl", str(tmp_path / "another.git"))
    before = refs(remote), state(root)
    result = invoke(root, "v0.1.0-rc.2", "--push")
    assert result.returncode and "exactly one push URL" in result.stderr
    assert (refs(remote), state(root)) == before


def test_lightweight_candidate_is_supported(release_repo):
    root, remote, _ = release_repo
    (root / "package.json").write_text(json.dumps({"version": "0.1.0-rc.3"}))
    git(root, "add", "package.json")
    git(root, "commit", "-qm", "Lightweight candidate")
    commit = git(root, "rev-parse", "HEAD")
    git(root, "tag", "v0.1.0-rc.3")
    git(root, "push", "-q", "origin", "refs/tags/v0.1.0-rc.3")
    before, remote_before = state(root), refs(remote)
    result = invoke(root, "v0.1.0-rc.3", "--push")
    assert result.returncode == 0, result.stderr
    assert refs(remote) == {**remote_before, "refs/tags/latest": commit}
    assert state(root) == before


def test_rejected_push_leaves_remote_and_local_refs_unchanged(release_repo):
    root, remote, _ = release_repo
    hook = remote / "hooks/pre-receive"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    before = refs(remote), state(root)
    result = invoke(root, "v0.1.0-rc.2", "--push")
    assert result.returncode and "rejected" in result.stderr
    assert (refs(remote), state(root)) == before


@pytest.mark.parametrize("exists", [False, True])
def test_concurrent_channel_creation_or_move_is_not_overwritten(release_repo, monkeypatch, exists):
    root, remote, commits = release_repo
    if exists:
        git(root, "push", "-q", "origin", "refs/tags/v0.1.0-rc.1:refs/tags/latest")
    before = state(root)
    original = promotion.git

    def concurrent(repo, *args):
        if args[0] == "push":
            git(remote, "update-ref", "refs/tags/latest", commits[0])
        return original(repo, *args)

    monkeypatch.setattr(promotion, "git", concurrent)
    with pytest.raises(ValueError, match="stale info|rejected|failed to push"):
        promotion.promote(root, "v0.1.0-rc.2", push=True)
    assert refs(remote)["refs/tags/latest"] == commits[0]
    assert state(root) == before

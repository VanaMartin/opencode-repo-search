"""Installed native-default capture for independent local collection registries.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from repo_search.git_source import MainSource
from repo_search.local_registry import LocalRegistry, digest
from repo_search.settings import database_path
from test_local_source import local_repo as local_repo
from test_package import git, launch
from test_package import package as package
from test_package import project as project

POLICY = {"parser": "source", "include": ["*.py"], "exclude": [], "extensions": [".py"]}


def operation(package, root, action, *, options=None, env=None, extra="", check=True):
    script = (
        """
import json
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from local_collections import preview, create
root = Path(sys.argv[2])
policy = json.loads(sys.argv[3])
options = json.loads(sys.argv[4])
"""
        + extra
        + """
action = {'preview': preview, 'create': create}[sys.argv[5]]
result = action(root, 'co-experiment', policy, **options)
assert 'torch' not in sys.modules and 'lancedb' not in sys.modules
print(json.dumps(result))
"""
    )
    return subprocess.run(
        [
            sys.executable,
            "-S",
            "-c",
            script,
            str(package / "plugin"),
            str(root),
            json.dumps(POLICY),
            json.dumps(options or {}),
            action,
        ],
        capture_output=True,
        text=True,
        env=env,
        check=check,
        timeout=30,
    )


def normal_files(root):
    directory = root / ".opencode/search-package"
    return {p.name: p.read_bytes() for p in directory.iterdir() if p.is_file()}


def test_unconfigured_installed_adapter_needs_no_remote_runtime_or_model(
    package, local_repo, tmp_path
):
    env = {
        **os.environ,
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
    }
    plan = json.loads(operation(package, local_repo, "preview", env=env).stdout)
    assert plan["inspection"]["selected_files"] == 1
    assert not (local_repo / ".git/repo-search").exists()
    result = json.loads(
        operation(
            package, local_repo, "create", env=env, options={"expect_revision": plan["revision"]}
        ).stdout
    )
    assert result["applied"] and result["collection"]["ref"] == "refs/heads/experiment"
    assert not (tmp_path / "cache").exists() and not (tmp_path / "data").exists()
    assert not (local_repo / ".opencode").exists()
    assert not git(local_repo, "remote")


@pytest.mark.parametrize("private", [True, False])
@pytest.mark.parametrize("custom_db", [True, False])
def test_installed_adapter_captures_normal_database_without_policy_pin_or_config_edit(
    package,
    project,
    tmp_path,
    monkeypatch,
    private,
    custom_db,
):
    root = project
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("REPO_SEARCH_DB", raising=False)
    env = {
        **os.environ,
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }
    arguments = ["init", "git-ignore"]
    if custom_db:
        arguments.extend(["--db", str(tmp_path / "existing database")])
    launch(package, root, *arguments, env=env)
    runtime = root / ".opencode/search-package/runtime.json"
    settings = json.loads(runtime.read_bytes())
    if not private:
        settings["policy_source"] = "upstream"
        runtime.write_text(json.dumps(settings))
    profile = json.loads((runtime.parent / "profiles.json").read_bytes())
    policy_hash = (
        digest((json.dumps(profile, sort_keys=True, ensure_ascii=False) + "\n").encode())
        if private
        else None
    )
    source = MainSource.discover(root, profile=settings["profile"], policy_hash=policy_hash)
    expected = database_path(source, Path(settings["db"]) if custom_db else None)
    before = normal_files(root), git(root, "status", "--porcelain=v1"), git(root, "show-ref")
    plan = json.loads(operation(package, root, "preview", env=env).stdout)
    assert plan["database"] == str(expected)
    result = json.loads(
        operation(
            package, root, "create", env=env, options={"expect_revision": plan["revision"]}
        ).stdout
    )
    entry = result["collection"]
    assert (
        entry["database"] == str(expected) and entry["profile"]["embedding"] == profile["embedding"]
    )
    assert before == (
        normal_files(root),
        git(root, "status", "--porcelain=v1"),
        git(root, "show-ref"),
    )
    assert not (root / ".git/repo-search/policies").exists()
    assert not (tmp_path / "cache").exists() and not expected.exists()
    # Later normal changes do not silently relocate or retarget the captured collection.
    settings["db"] = str(tmp_path / "later database")
    runtime.write_text(json.dumps(settings))
    assert LocalRegistry.discover(root).status("co-experiment")["database"] == str(expected)


def test_normal_configuration_edits_invalidate_reviewed_creation(package, project, tmp_path):
    launch(package, project, "init", "git-ignore")
    plan = json.loads(operation(package, project, "preview").stdout)
    runtime = project / ".opencode/search-package/runtime.json"
    settings = json.loads(runtime.read_bytes())
    settings["db"] = str(tmp_path / "different")
    runtime.write_text(json.dumps(settings))
    result = operation(
        package, project, "create", options={"expect_revision": plan["revision"]}, check=False
    )
    assert result.returncode and "changed since preview" in result.stderr
    assert not LocalRegistry.discover(project).directory.exists()


def test_configuration_is_rechecked_after_waiting_for_registry_lock(package, project, tmp_path):
    launch(package, project, "init", "git-ignore")
    plan = json.loads(operation(package, project, "preview").stdout)
    extra = """
from contextlib import contextmanager
from repo_search.local_registry import LocalRegistry
original = LocalRegistry.lock
@contextmanager
def changed(self):
    with original(self):
        path = root / '.opencode/search-package/runtime.json'
        document = json.loads(path.read_bytes())
        document['branch'] = 'changed-while-waiting'
        path.write_text(json.dumps(document))
        yield
LocalRegistry.lock = changed
"""
    result = operation(
        package,
        project,
        "create",
        options={"expect_revision": plan["revision"]},
        extra=extra,
        check=False,
    )
    assert result.returncode and "configuration changed since preview" in result.stderr
    assert not LocalRegistry.discover(project).path.exists()


def test_inherited_native_settings_do_not_share_local_registry(package, project, tmp_path):
    launch(package, project, "init", "git-ignore", "--scope", "repository")
    worker = tmp_path / "linked worker"
    git(project, "worktree", "add", "-qb", "worker", str(worker), "HEAD")
    configuration = project / ".git/repo-search/package.json"
    before = configuration.read_bytes()
    entries = []
    for root in (project, worker):
        plan = json.loads(operation(package, root, "preview").stdout)
        entry = json.loads(
            operation(package, root, "create", options={"expect_revision": plan["revision"]}).stdout
        )["collection"]
        entries.append(entry)
    assert entries[0]["database"] == entries[1]["database"]
    assert (
        entries[0]["id"] != entries[1]["id"]
        and entries[0]["worktree_id"] != entries[1]["worktree_id"]
    )
    assert configuration.read_bytes() == before
    assert not (project / ".git/repo-search/policies").exists()

"""Repository-private discovery, adoption, overrides and installed worktree MCPs.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import asyncio
import json
import os
import subprocess
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from repo_search.git_source import MainSource, pin_profile
from repo_search.settings import database_path
from test_package import git, launch
from test_package import package as package
from test_package import project as project


def linked(root, path):
    git(root, "worktree", "add", "-q", "-b", path.name.replace(" ", "-"), str(path), "HEAD")
    return path


def configuration(package, root, **kwargs):
    return json.loads(launch(package, root, "configuration", **kwargs).stdout)


def repository_file(root):
    return (
        root / git(root, "rev-parse", "--git-common-dir")
    ).resolve() / "repo-search/package.json"


def test_repository_scope_is_explicit_atomic_and_inherited(package, project, tmp_path):
    root = project
    worker = linked(root, tmp_path / "worker with spaces")
    before = git(root, "status", "--porcelain=v1"), git(root, "rev-parse", "HEAD")
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path / "unused-cache")}
    missing = json.loads(launch(package, worker, "status", env=env).stdout)
    assert missing["readiness"] == "not_configured"
    assert missing["configuration"]["source"] == "none"
    preview = json.loads(
        launch(
            package, root, "init", "git-ignore", "--scope", "repository", "--dry-run", env=env
        ).stdout
    )
    assert preview["dry_run"] and "next_steps" not in preview
    assert not repository_file(root).parent.exists()
    applied = json.loads(
        launch(package, root, "init", "git-ignore", "--scope", "repository", env=env).stdout
    )
    assert "Git common directory" in applied["next"]
    first, second = configuration(package, root, env=env), configuration(package, worker, env=env)
    assert first["source"] == second["source"] == "repository-private"
    assert not first["inherited"] and second["inherited"]
    assert first["settings"] == second["settings"] and first["profile"] == second["profile"]
    assert first["path"] == second["path"] == str(repository_file(root))
    assert second["root"] == str(worker)
    javascript = json.loads(
        subprocess.check_output(
            [
                "node",
                "--input-type=module",
                "-e",
                "const {resolveConfiguration} = await import(process.argv[1]); "
                "console.log(JSON.stringify(await resolveConfiguration(process.argv[2])))",
                (package / "plugin/configuration.js").as_uri(),
                str(worker),
            ],
            text=True,
        )
    )
    assert javascript == second
    assert not (root / ".opencode").exists() and not (worker / ".opencode").exists()
    assert not (tmp_path / "unused-cache").exists()
    assert before == (git(root, "status", "--porcelain=v1"), git(root, "rev-parse", "HEAD"))
    assert not list(repository_file(root).parent.glob("*.install-tmp"))
    rejected = launch(package, worker, "init", "git-commit", "--scope", "repository", check=False)
    assert rejected.returncode and "private" in rejected.stderr
    original = repository_file(root).read_bytes()
    repository_file(root).write_text("null")
    invalid = launch(package, worker, "configuration", check=False)
    assert invalid.returncode and "Unsupported repository-private" in invalid.stderr
    repository_file(root).write_bytes(original)


def test_scope_adoption_preserves_policy_identity_and_local_files(package, project, tmp_path):
    root = project
    worker = linked(root, tmp_path / "worker")
    launch(package, root, "init", "git-ignore")
    directory = root / ".opencode/search-package"
    original = {path.name: path.read_bytes() for path in directory.iterdir()}
    config = configuration(package, root)
    old_source = MainSource.discover(
        root, profile=config["settings"]["profile"], policy_source="local"
    )
    assert configuration(package, worker)["source"] == "none"
    rejected = launch(package, root, "init", "git-ignore", "--scope", "repository", check=False)
    assert rejected.returncode and "--adopt" in rejected.stderr
    launch(package, root, "init", "git-ignore", "--scope", "repository", "--adopt")
    inherited = configuration(package, worker)
    new_source = MainSource.discover(
        worker,
        profile=inherited["settings"]["profile"],
        policy_hash=pin_profile(worker, inherited["profile"]),
    )
    assert old_source.owner == new_source.owner
    assert database_path(old_source) == database_path(new_source)
    assert configuration(package, root)["source"] == "repository-private"
    assert original == {path.name: path.read_bytes() for path in directory.iterdir()}
    # Explicit worktree setup opts back into the preserved private override.
    launch(package, root, "init", "git-ignore", "--scope", "worktree")
    assert configuration(package, root)["source"] == "worktree-private"
    assert configuration(package, worker)["source"] == "repository-private"


def test_worktree_policy_override_is_isolated(package, project, tmp_path):
    root = project
    worker = linked(root, tmp_path / "worker")
    launch(package, root, "init", "git-ignore", "--scope", "repository")
    launch(package, worker, "init", "git-ignore", "--scope", "worktree")
    path = worker / ".opencode/search-package/profiles.json"
    policy = json.loads(path.read_bytes())
    policy["corpora"]["repository"]["include"] = ["src/**"]
    path.write_text(json.dumps(policy))
    first, second = configuration(package, root), configuration(package, worker)
    assert first["source"] == "repository-private" and second["source"] == "worktree-private"
    sources = [
        MainSource.discover(
            Path(item["root"]),
            profile=item["settings"]["profile"],
            policy_hash=pin_profile(Path(item["root"]), item["profile"]),
        )
        for item in (first, second)
    ]
    assert sources[0].table != sources[1].table
    assert database_path(sources[0]) != database_path(sources[1])


def test_repository_private_precedes_committed_settings_without_changing_them(
    package, project, tmp_path
):
    root = project
    launch(package, root, "init", "git-commit")
    directory = root / ".opencode/search-package"
    before = {path.name: path.read_bytes() for path in directory.iterdir()}
    worker = linked(root, tmp_path / "worker")
    assert configuration(package, worker)["source"] == "committed"
    launch(package, root, "init", "git-ignore", "--scope", "repository", "--adopt")
    launch(
        package,
        root,
        "init",
        "git-ignore",
        "--scope",
        "repository",
        "--db",
        str(tmp_path / "shared-db"),
    )
    assert configuration(package, worker)["source"] == "repository-private"
    assert configuration(package, worker)["settings"]["db"] == str(tmp_path / "shared-db")
    assert before == {path.name: path.read_bytes() for path in directory.iterdir()}
    assert not git(root, "status", "--porcelain=v1")
    assert (
        json.loads(launch(package, worker, "init").stdout)["configuration"]["source"]
        == "repository-private"
    )
    launch(package, root, "init", "git-ignore", "--scope", "repository", "--adopt")
    assert configuration(package, worker)["settings"]["db"] == str(tmp_path / "shared-db")
    proposal = tmp_path / "shared-policy-edit.json"
    proposal.write_text(json.dumps({"description": "Publishable shared edit"}))
    args = ("corpus", "update", "repository", "--spec", str(proposal))
    preview = json.loads(launch(package, worker, *args).stdout)
    assert any("current worktree" in warning for warning in preview["warnings"])
    result = json.loads(
        launch(
            package, worker, *args, "--apply", "--expect-revision", preview["revision"], "--sync"
        ).stdout
    )
    assert result["sync"]["state"] == "publication_required"
    policy_file = worker / ".opencode/search-package/profiles.json"
    policy = json.loads(policy_file.read_bytes())
    assert policy["corpora"]["repository"]["description"] == "Publishable shared edit"
    assert configuration(package, worker)["profile"] == policy
    assert not git(worker, "diff", "--cached")
    assert before == {path.name: path.read_bytes() for path in directory.iterdir()}
    # Never overwrite unrelated edits to the worktree's publishable policy.
    policy["corpora"]["repository"]["description"] = "Unrelated local edit"
    policy_file.write_text(json.dumps(policy))
    raw = repository_file(root).read_bytes()
    proposal.write_text(json.dumps({"description": "Second shared edit"}))
    preview = json.loads(launch(package, worker, *args).stdout)
    rejected = launch(
        package, worker, *args, "--apply", "--expect-revision", preview["revision"], check=False
    )
    assert rejected.returncode and "reconcile" in rejected.stderr
    assert raw == repository_file(root).read_bytes()
    assert json.loads(policy_file.read_bytes()) == policy


def test_concurrent_repository_initialization_and_corpus_edits(package, project, tmp_path):
    root = project
    workers = [linked(root, tmp_path / f"worker-{index}") for index in range(3)]
    processes = [
        subprocess.Popen(
            [
                sys.executable,
                str(package / "plugin/launch.py"),
                "init",
                "git-ignore",
                "--scope",
                "repository",
                "--root",
                str(worker),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for worker in workers
    ]
    outputs = [process.communicate(timeout=60) for process in processes]
    assert all(process.returncode == 0 for process in processes), outputs
    configs = [configuration(package, worker) for worker in workers]
    assert all(item["settings"] == configs[0]["settings"] for item in configs)
    raw = repository_file(root).read_bytes()
    proposal = tmp_path / "proposal.json"
    proposal.write_text(json.dumps({"description": "Reviewed description"}))
    preview = json.loads(
        launch(
            package, workers[0], "corpus", "update", "repository", "--spec", str(proposal)
        ).stdout
    )
    assert raw == repository_file(root).read_bytes()
    launch(
        package,
        workers[1],
        "corpus",
        "update",
        "repository",
        "--spec",
        str(proposal),
        "--apply",
        "--expect-revision",
        preview["revision"],
    )
    assert (
        configuration(package, workers[2])["profile"]["corpora"]["repository"]["description"]
        == "Reviewed description"
    )
    stale = launch(
        package,
        workers[0],
        "corpus",
        "update",
        "repository",
        "--spec",
        str(proposal),
        "--apply",
        "--expect-revision",
        preview["revision"],
        check=False,
    )
    assert stale.returncode and "changed" in stale.stderr
    assert all(not (worker / ".opencode").exists() for worker in workers)


def test_inherited_installed_mcps_share_index_and_survive_origin_worktree_removal(
    package, project, tmp_path
):
    root = project
    origin = linked(root, tmp_path / "origin-worker")
    worker = linked(root, tmp_path / "other-worker")
    db = tmp_path / "db"
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path / "cache")}
    launch(package, origin, "init", "git-ignore", "--scope", "repository", "--db", str(db), env=env)
    # The checked-out feature branch and dirty files must not change the indexed source.
    (worker / "src/feature.py").write_text("featureonlymarker = True\n")
    git(worker, "add", "src/feature.py")
    git(worker, "commit", "-qm", "unpublished feature")
    (worker / "src/dirty.py").write_text("dirtyonlymarker = True\n")

    async def exercise():
        async with AsyncExitStack() as stack:
            clients = []
            for worktree in (origin, worker):
                streams = await stack.enter_async_context(
                    stdio_client(
                        StdioServerParameters(
                            command=sys.executable,
                            args=[
                                str(package / "plugin/launch.py"),
                                "mcp",
                                "--root",
                                str(worktree),
                            ],
                            cwd=worktree,
                            env=env,
                        )
                    )
                )
                client = await stack.enter_async_context(ClientSession(*streams))
                await client.initialize()
                result = await client.call_tool(
                    "query_table", {"query": "symbolic ordering", "query_type": "fts"}
                )
                assert not result.isError, result
                assert json.loads(result.content[0].text)["results"][0]["path"] == "src/solver.py"
                clients.append(client)
            details = [
                json.loads((await client.call_tool("table_details", {})).content[0].text)
                for client in clients
            ]
            assert details[0]["service"]["pid"] == details[1]["service"]["pid"]
            assert all(item["service"]["loaded_models"] == 1 for item in details)
            assert all(
                item["freshness"]["source_commit"] == git(root, "rev-parse", "origin/main")
                for item in details
            )
            hidden = await clients[1].call_tool(
                "query_table", {"query": "featureonlymarker", "query_type": "fts"}
            )
            assert not json.loads(hidden.content[0].text)["results"]
            hidden = await clients[1].call_tool(
                "query_table", {"query": "dirtyonlymarker", "query_type": "fts"}
            )
            assert not json.loads(hidden.content[0].text)["results"]
            git(root, "worktree", "remove", str(origin))
            deadline = time.monotonic() + 10
            while True:
                detail = json.loads(
                    (await clients[1].call_tool("table_details", {})).content[0].text
                )
                mounts = detail["service"]["corpora"][detail["name"]]["mounts"]
                if mounts == 1:
                    break
                assert time.monotonic() < deadline
                await asyncio.sleep(0.2)
            result = await clients[1].call_tool(
                "query_table", {"query": "symbolic ordering", "query_type": "fts"}
            )
            assert not result.isError and json.loads(result.content[0].text)["results"]
            assert configuration(package, worker, env=env)["source"] == "repository-private"
            status = json.loads(launch(package, worker, "status", env=env).stdout)
            assert status["configuration"]["inherited"]
            assert status["ready_for_queries"] and status["mcp"]["state"] == "not_checked"
            # Explicit CLI selection still outranks the inherited database setting.
            alternate = json.loads(
                launch(
                    package, worker, "catalog", "--db", str(tmp_path / "other-db"), env=env
                ).stdout
            )
            assert alternate["db_uri"] == str(tmp_path / "other-db")
            selected = json.loads(
                launch(
                    package, worker, "status", "--db=" + str(tmp_path / "other-db"), env=env
                ).stdout
            )
            assert selected["configuration"]["overrides"] == {"db": str(tmp_path / "other-db")}
            # A failed upstream refresh must not damage the older shared publication.
            (root / "src/solver.py").write_text("def invalid(:\n")
            git(root, "commit", "-qam", "malformed upstream source")
            git(root, "push", "-q", "origin", "main")
            failed = launch(package, worker, "sync", env=env, check=False)
            assert failed.returncode
            stale = json.loads(launch(package, worker, "status", env=env).stdout)
            assert stale["snapshot_id"] == status["snapshot_id"]
            assert stale["ready_for_queries"] and stale["integrity"] == "complete"
            assert stale["upstream"]["state"] == "behind"
            assert stale["refresh"]["state"] == "failed" and stale["refresh"]["error"]
            retained = await clients[1].call_tool(
                "query_table", {"query": "symbolic ordering", "query_type": "fts"}
            )
            assert not retained.isError and json.loads(retained.content[0].text)["results"]

    try:
        asyncio.run(exercise())
    finally:
        launch(package, worker, "service", "stop", env=env)
        launch(package, worker, "service", "stop", "--db", str(tmp_path / "other-db"), env=env)

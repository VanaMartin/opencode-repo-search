"""Exercise installed corpus management, additive edits and live MCP reconciliation.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from test_package import git, launch
from test_package import package as package
from test_package import project as project


@pytest.fixture
def managed(package, project, tmp_path):
    for name, body in {
        "kb/first/guide.md": "# Grounding\n\nFirstcorpusmarker evidence and source grounding.\n",
        "knowledge/second/guide.md": "# Expansion\n\n"
        "Secondcorpusmarker broader reference coverage.\n",
        "docs/papers/paper.md": "# Paper\n\n**Source:** https://example.invalid/paper\n\n"
        "**Pagination:** Printed pages 1–2.\n\nPrinted p. 2: Scientific note evidence.\n",
        "docs/mixed/invalid.md": "# Inventory\nNo source or pagination declarations.\n",
    }.items():
        path = project / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    git(project, "add", ".")
    git(project, "commit", "-qm", "add committed corpus inputs")
    git(project, "push", "-q", "origin", "main")
    env = {
        **os.environ,
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "HF_HOME": os.environ.get("HF_HOME", str(Path.home() / ".cache/huggingface")),
    }
    launch(package, project, "init", "git-ignore", "--db", str(tmp_path / "db"), env=env)
    return project, env


def reference(**changes):
    return {
        "enabled": True,
        "server": "team-notes",
        "parser": "source",
        "source_kind": "reference",
        "description": "Independent reference notes",
        "include": ["kb/first/**"],
        "exclude": [],
        "extensions": [".md"],
        **changes,
    }


def edit(package, managed, tmp_path, operation, name, spec, *flags, check=True):
    root, env = managed
    path = tmp_path / "proposal.json"
    path.write_text(json.dumps(spec))
    return launch(
        package, root, "corpus", operation, name, "--spec", str(path), *flags, env=env, check=check
    )


def files(root):
    return {
        name: (root / ".opencode/search-package" / name).read_bytes()
        for name in ("profiles.json", "runtime.json", "install.json")
    }


def test_corpus_inspect_and_preview_are_read_only(package, managed, tmp_path):
    root, env = managed
    original = files(root), git(root, "status", "--porcelain=v1")
    inspected = json.loads(launch(package, root, "corpus", "inspect", env=env).stdout)
    assert inspected["profile_path"] == ".opencode/search-package/profiles.json"
    assert inspected["inspection"]["basis"] == "cached_upstream"
    preview = json.loads(
        edit(package, managed, tmp_path, "add", "notes", reference(), "--dry-run", "--sync").stdout
    )
    assert not preview["applied"] and preview["sync"]["state"] == "preview"
    assert preview["base_revision"] == inspected["revision"]
    assert preview["changes"]["notes"]["before"] is None
    assert preview["inspection"]["corpora"]["notes"]["selected_files"] == 1
    assert preview["sync_corpora"] == ["repository", "notes"]
    assert any("private policy hash" in warning for warning in preview["warnings"])
    assert original == (files(root), git(root, "status", "--porcelain=v1"))
    assert not (root / ".git/repo-search").exists()
    assert not (tmp_path / "cache").exists()


def test_corpus_add_preserves_work_settings_and_unrelated_policy(package, managed, tmp_path):
    root, env = managed
    (root / "AGENTS.md").write_text("# Staged team edit\n")
    git(root, "add", "AGENTS.md")
    (root / "AGENTS.md").write_text("# Dirty team edit\n")
    before = files(root)
    state = (
        git(root, "diff", "--cached"),
        git(root, "status", "--porcelain=v1"),
        git(root, "rev-parse", "HEAD"),
    )
    preview = json.loads(edit(package, managed, tmp_path, "add", "notes", reference()).stdout)
    missing = edit(package, managed, tmp_path, "add", "notes", reference(), "--apply", check=False)
    assert missing.returncode and "--expect-revision" in missing.stderr
    assert files(root) == before
    result = json.loads(
        edit(
            package,
            managed,
            tmp_path,
            "add",
            "notes",
            reference(),
            "--apply",
            "--expect-revision",
            preview["revision"],
        ).stdout
    )
    assert result["applied"] and result["sync"]["state"] == "not_requested"
    after = files(root)
    assert after["runtime.json"] == before["runtime.json"]
    policy = json.loads(after["profiles.json"])
    assert policy.pop("corpora") == {
        **json.loads(before["profiles.json"])["corpora"],
        "notes": reference(),
    }
    assert policy == {
        key: value for key, value in json.loads(before["profiles.json"]).items() if key != "corpora"
    }
    metadata = json.loads(after["install.json"])
    assert (
        metadata["files"][".opencode/search-package/profiles.json"]
        == hashlib.sha256(after["profiles.json"]).hexdigest()
    )
    assert state == (
        git(root, "diff", "--cached"),
        git(root, "status", "--porcelain=v1"),
        git(root, "rev-parse", "HEAD"),
    )
    assert (root / "AGENTS.md").read_text() == "# Dirty team edit\n"
    assert not (tmp_path / "cache").exists()


def test_update_appends_by_default_and_replaces_only_explicitly(package, managed, tmp_path):
    root, _ = managed
    original = json.loads(files(root)["profiles.json"])
    patch = {"include": ["knowledge/second/**"], "enabled": True, "extensions": [".txt", ".md"]}
    plan = json.loads(edit(package, managed, tmp_path, "update", "references", patch).stdout)
    changed = plan["changes"]["references"]["after"]
    assert changed["include"] == [
        *original["corpora"]["references"]["include"],
        "knowledge/second/**",
    ]
    assert changed["server"] == "lancedb-references"
    edit(
        package,
        managed,
        tmp_path,
        "update",
        "references",
        patch,
        "--apply",
        "--expect-revision",
        plan["revision"],
    )
    plan = json.loads(edit(package, managed, tmp_path, "update", "references", patch).stdout)
    assert not plan["changed"] and plan["changes"] == {}
    plan = json.loads(
        edit(package, managed, tmp_path, "update", "references", patch, "--replace-lists").stdout
    )
    assert plan["changes"]["references"]["after"]["include"] == ["knowledge/second/**"]
    assert list(plan["changes"]) == ["references"]


@pytest.mark.parametrize("settings_changed", [False, True])
def test_corpus_apply_rejects_stale_policy_or_settings(
    package, managed, tmp_path, settings_changed
):
    root, _ = managed
    plan = json.loads(edit(package, managed, tmp_path, "add", "notes", reference()).stdout)
    name = "runtime.json" if settings_changed else "profiles.json"
    path = root / ".opencode/search-package" / name
    path.write_bytes(path.read_bytes() + b"\n")
    current = files(root)
    result = edit(
        package,
        managed,
        tmp_path,
        "add",
        "notes",
        reference(),
        "--apply",
        "--expect-revision",
        plan["revision"],
        check=False,
    )
    assert result.returncode and "changed since preview" in result.stderr
    assert files(root) == current


def test_review_revision_binds_exact_proposal(package, managed, tmp_path):
    root, _ = managed
    plan = json.loads(edit(package, managed, tmp_path, "add", "notes", reference()).stdout)
    original = files(root)
    changed = reference(include=["knowledge/second/**"])
    rejected = edit(
        package,
        managed,
        tmp_path,
        "add",
        "notes",
        changed,
        "--apply",
        "--expect-revision",
        plan["revision"],
        check=False,
    )
    assert rejected.returncode and "proposal changed since preview" in rejected.stderr
    assert files(root) == original


def test_concurrent_corpus_edits_cannot_overwrite_each_other(package, managed, tmp_path):
    root, env = managed
    commands = []
    for name in ("alpha", "beta"):
        spec = reference(server="team-" + name)
        plan = json.loads(edit(package, managed, tmp_path, "add", name, spec).stdout)
        path = tmp_path / (name + ".json")
        path.write_text(json.dumps(spec))
        commands.append(
            [
                sys.executable,
                str(package / "plugin/launch.py"),
                "corpus",
                "add",
                name,
                "--spec",
                str(path),
                "--root",
                str(root),
                "--apply",
                "--expect-revision",
                plan["revision"],
            ]
        )
    processes = [
        subprocess.Popen(
            command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for command in commands
    ]
    try:
        outputs = [process.communicate(timeout=30) for process in processes]
        assert sorted(process.returncode for process in processes) == [0, 1], outputs
        policy = json.loads(files(root)["profiles.json"])
        assert len({"alpha", "beta"}.intersection(policy["corpora"])) == 1
    finally:
        for process in processes:
            if process.poll() is None:
                process.kill()
                process.wait()


def test_disabled_empty_corpus_can_be_prepared_without_mounting(package, managed, tmp_path):
    root, _ = managed
    spec = reference(enabled=False, include=["future/**"])
    plan = json.loads(edit(package, managed, tmp_path, "add", "notes", spec).stdout)
    assert not plan["validation_errors"]
    result = json.loads(
        edit(
            package,
            managed,
            tmp_path,
            "add",
            "notes",
            spec,
            "--apply",
            "--expect-revision",
            plan["revision"],
        ).stdout
    )
    assert result["applied"]
    assert not json.loads(files(root)["profiles.json"])["corpora"]["notes"]["enabled"]
    assert not (tmp_path / "cache").exists()


@pytest.mark.parametrize(
    "operation,name,spec,message",
    [
        ("add", "repository", reference(), "already exists"),
        ("update", "missing", {"enabled": True}, "Unknown corpus"),
        ("add", "Not-Valid", reference(), "lowercase"),
        ("add", "notes", reference(server="lancedb"), "distinct MCP"),
        ("add", "notes", reference(include=["../outside/**"]), "within the repository"),
        ("add", "notes", reference(include=["/outside/**"]), "within the repository"),
        ("add", "notes", reference(extensions=[".pdf"]), "PDF/binary"),
        ("add", "notes", {"enabled": True}, "Unknown parser"),
        ("update", "repository", {"parser": "reference_note"}, "new corpus"),
        ("update", "repository", {"server": "renamed"}, "new corpus"),
        ("update", "repository", {"embedding": {}}, "supported policy fields"),
        ("update", "repository", {"include": "docs/**"}, "list of strings"),
    ],
)
def test_invalid_corpus_edits_never_write(
    package, managed, tmp_path, operation, name, spec, message
):
    root, _ = managed
    before = files(root)
    result = edit(package, managed, tmp_path, operation, name, spec, check=False)
    assert result.returncode and message in result.stderr
    assert files(root) == before
    assert not (tmp_path / "cache").exists()


def test_scientific_notes_validation_and_explicit_overlap_changes(package, managed, tmp_path):
    valid = reference(
        server="scientific-papers", parser="reference_note", include=["docs/papers/**"]
    )
    overlap = json.loads(edit(package, managed, tmp_path, "add", "papers", valid).stdout)
    assert list(overlap["changes"]) == ["papers"]
    assert overlap["inspection"]["overlapping_files"] == {"repository, papers": 1}
    explicit = json.loads(
        edit(
            package, managed, tmp_path, "add", "papers", valid, "--exclude-from", "repository"
        ).stdout
    )
    assert explicit["inspection"]["overlapping_files"] == {}
    assert "docs/papers/**" in explicit["changes"]["repository"]["after"]["exclude"]
    root, _ = managed
    for selection in ["docs/mixed/**", "missing/**"]:
        invalid = {**valid, "include": [selection]}
        before = files(root)
        plan = json.loads(edit(package, managed, tmp_path, "add", "papers", invalid).stdout)
        assert plan["validation_errors"]
        rejected = edit(
            package,
            managed,
            tmp_path,
            "add",
            "papers",
            invalid,
            "--apply",
            "--expect-revision",
            plan["revision"],
            check=False,
        )
        assert rejected.returncode and files(root) == before


def test_corpus_add_refuses_unmanaged_mcp_collision(package, managed, tmp_path):
    root, _ = managed
    config = root / "opencode.jsonc"
    config.write_text('{"mcp":{"servers":{"team-notes":{"type":"local","command":["custom"]}}}}')
    before = files(root), config.read_bytes()
    rejected = edit(package, managed, tmp_path, "add", "notes", reference(), check=False)
    assert rejected.returncode and "conflicts" in rejected.stderr
    assert before == (files(root), config.read_bytes())


def test_shared_corpus_change_defers_sync_without_touching_git(package, managed, tmp_path):
    root, env = managed
    launch(package, root, "init", "git-commit", env=env)
    before = git(root, "diff", "--cached"), git(root, "rev-parse", "HEAD")
    plan = json.loads(edit(package, managed, tmp_path, "add", "notes", reference()).stdout)
    result = json.loads(
        edit(
            package,
            managed,
            tmp_path,
            "add",
            "notes",
            reference(),
            "--apply",
            "--expect-revision",
            plan["revision"],
            "--sync",
        ).stdout
    )
    assert result["applied"] and result["publication_required"]
    assert result["sync"]["state"] == "publication_required"
    assert before == (git(root, "diff", "--cached"), git(root, "rev-parse", "HEAD"))
    assert not (tmp_path / "cache").exists()


def test_failed_sync_reports_applied_policy_without_ready_runtime(package, managed, tmp_path):
    root, env = managed
    binary = tmp_path / "bin"
    binary.mkdir()
    uv = binary / "uv"
    uv.write_text("#!/bin/sh\nexit 17\n")
    uv.chmod(0o755)
    env["PATH"] = str(binary) + os.pathsep + env["PATH"]
    plan = json.loads(edit(package, managed, tmp_path, "add", "notes", reference()).stdout)
    failed = edit(
        package,
        managed,
        tmp_path,
        "add",
        "notes",
        reference(),
        "--apply",
        "--expect-revision",
        plan["revision"],
        "--sync",
        check=False,
    )
    result = json.loads(failed.stdout)
    assert failed.returncode and result["applied"] and result["sync"]["state"] == "failed"
    assert "notes" in json.loads(files(root)["profiles.json"])["corpora"]
    assert not list((tmp_path / "cache").glob("**/ready.json"))


def test_add_broaden_and_resync_live_corpus_reuses_daemon_model(package, managed, tmp_path):
    root, env = managed

    async def exercise():
        async with AsyncExitStack() as stack:

            async def connect(corpus):
                streams = await stack.enter_async_context(
                    stdio_client(
                        StdioServerParameters(
                            command=sys.executable,
                            args=[
                                str(package / "plugin/launch.py"),
                                "mcp",
                                "--root",
                                str(root),
                                "--corpus",
                                corpus,
                            ],
                            cwd=root,
                            env=env,
                        )
                    )
                )
                session = await stack.enter_async_context(ClientSession(*streams))
                await session.initialize()
                return session

            async def tool(client, name, **arguments):
                result = await client.call_tool(name, arguments)
                assert not result.isError, result
                return json.loads(result.content[0].text)

            original = await connect("repository")
            await tool(original, "query_table", query="symbolic ordering")
            initial = await tool(original, "table_details")
            for operation, spec, marker, expected in (
                ("add", reference(), "firstcorpusmarker", "kb/first/guide.md"),
                (
                    "update",
                    {"include": ["knowledge/second/**"]},
                    "secondcorpusmarker",
                    "knowledge/second/guide.md",
                ),
            ):
                plan = json.loads(edit(package, managed, tmp_path, operation, "notes", spec).stdout)
                process = await asyncio.to_thread(
                    edit,
                    package,
                    managed,
                    tmp_path,
                    operation,
                    "notes",
                    spec,
                    "--apply",
                    "--expect-revision",
                    plan["revision"],
                    "--sync",
                )
                result = json.loads(process.stdout)
                assert result["sync"]["state"] == "complete"
                assert set(result["sync"]["results"]) == {"repository", "notes"}
                client = await connect("notes")
                query = await tool(client, "query_table", query=marker, query_type="fts")
                assert query["results"][0]["path"] == expected
                details = await tool(client, "table_details")
                assert details["service"]["pid"] == initial["service"]["pid"]
                assert details["service"]["loaded_models"] == 1
            # Old pinned connections retain their last complete snapshot.
            assert (await tool(original, "table_details"))["freshness"]["integrity"] == "complete"

    try:
        asyncio.run(exercise())
    finally:
        launch(package, root, "service", "stop", env=env)

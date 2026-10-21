"""Verify the npm-installed artifact, isolated bootstrap and real MCP launch path.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import tarfile
import time
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BUNDLE = Path(__file__).resolve().parents[1]


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    directory = tmp_path_factory.mktemp("npm artifact with spaces")
    report = json.loads(
        subprocess.check_output(
            ["npm", "pack", "--json", "--pack-destination", str(directory)],
            cwd=BUNDLE,
            text=True,
        )
    )[0]
    archive = directory / report["filename"]
    with tarfile.open(archive) as packed:
        names = {member.name.removeprefix("package/") for member in packed.getmembers()}
    required = {
        "package.json",
        "LICENSE",
        "README.md",
        "index.js",
        "plugin/index.js",
        "plugin/launch.py",
        "plugin/bootstrap.py",
        "plugin/project.py",
        "plugin/migration.py",
        "plugin/suggestions.py",
        "plugin/corpora.py",
        "payload/.opencode/search/registration.js",
        "payload/.opencode/search/uv.lock",
        "payload/.opencode/search/pyproject.toml",
        "payload/.opencode/search/repo_search/core.py",
        "payload/docs/agent-search.md",
        "payload/.claude/skills/repo-knowledge-search/SKILL.md",
    }
    assert required <= names
    forbidden = {".venv", "__pycache__", "node_modules", ".git", "tests", ".pytest_cache"}
    assert all(not forbidden.intersection(Path(name).parts) for name in names)
    subprocess.run(
        [
            "npm",
            "install",
            "--prefix",
            str(directory / "installed"),
            "--ignore-scripts",
            "--no-audit",
            "--no-fund",
            "--package-lock=false",
            str(archive),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return directory / "installed/node_modules/opencode-repo-search"


@pytest.fixture
def project(tmp_path):
    upstream, root = tmp_path / "upstream.git", tmp_path / "project with spaces"
    subprocess.run(
        ["git", "init", "--bare", "-q", "--initial-branch=main", str(upstream)], check=True
    )
    subprocess.run(["git", "clone", "-q", str(upstream), str(root)], check=True)
    git(root, "config", "user.name", "Search Test")
    git(root, "config", "user.email", "search@example.invalid")
    (root / "src").mkdir()
    (root / "src/solver.py").write_text(
        'def solve(matrix):\n    """Reuse symbolic ordering."""\n    return matrix\n'
    )
    (root / "AGENTS.md").write_text("# Shared team rules\n")
    (root / "opencode.jsonc").write_text('{\n // Team configuration\n "mcp": {}\n}\n')
    git(root, "add", ".")
    git(root, "commit", "-qm", "initialize fixture")
    git(root, "push", "-q", "origin", "main")
    return root


def launch(package, root, *arguments, env=None, check=True):
    return subprocess.run(
        [sys.executable, str(package / "plugin/launch.py"), *arguments, "--root", str(root)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        check=check,
        timeout=180,
    )


def test_installed_entrypoint(package):
    subprocess.run(
        [
            "node",
            "--input-type=module",
            "-e",
            "import plugin from 'opencode-repo-search'; "
            "import { createRequire } from 'node:module'; "
            "import { pathToFileURL } from 'node:url'; "
            "const require = createRequire(import.meta.url); "
            "const local = await import(pathToFileURL(require.resolve("
            "'./node_modules/opencode-repo-search/index'))); "
            "if (local.default !== plugin) throw new Error('Directory/package exports differ'); "
            "if (plugin.id !== 'opencode-repo-search' || typeof plugin.setup !== 'function') "
            "throw new Error('Invalid package export')",
        ],
        cwd=package.parents[1],
        check=True,
    )
    subprocess.run(
        ["node", "--test", str(BUNDLE / "tests/test_plugin.mjs")],
        cwd=BUNDLE,
        env={**os.environ, "REPO_SEARCH_TEST_ENTRY": str(package / "plugin/index.js")},
        check=True,
    )


def test_package_init_is_explicit_and_preserves_local_work(package, project, tmp_path):
    root = project
    initial = git(root, "rev-parse", "HEAD")
    (root / "AGENTS.md").write_text("# Staged team edit\n")
    git(root, "add", "AGENTS.md")
    (root / "AGENTS.md").write_text("# Unstaged team edit\n")
    staged, status = git(root, "diff", "--cached"), git(root, "status", "--porcelain=v1")
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path / "cache")}
    result = json.loads(launch(package, root, "init", env=env).stdout)
    assert result["visibility"] == "undecided"
    assert "next_steps" not in result
    assert not (root / ".opencode").exists()
    preview = launch(package, root, "init", "git-ignore", "--dry-run", env=env)
    assert "next_steps" not in json.loads(preview.stdout)
    assert "Next steps:" not in preview.stderr
    assert not (root / ".opencode").exists()
    applied = launch(package, root, "init", "git-ignore", env=env)
    result = json.loads(applied.stdout)
    assert "Next steps:" in applied.stderr
    assert ".git/info/exclude (.gitignore is unchanged)" in applied.stderr
    for step in result["next_steps"]:
        assert step in applied.stderr
    assert any(step.startswith("/mcps") and "lancedb" in step for step in result["next_steps"])
    assert any(step.startswith("/search-sync") for step in result["next_steps"])
    assert any("ready_for_queries: true" in step for step in result["next_steps"])
    assert any("repo-knowledge-search" in step for step in result["next_steps"])
    assert not any("shared policy commit" in step for step in result["next_steps"])
    assert not (tmp_path / "cache").exists()
    assert git(root, "rev-parse", "HEAD") == initial
    assert git(root, "diff", "--cached") == staged
    assert git(root, "status", "--porcelain=v1") == status
    assert (root / "AGENTS.md").read_text() == "# Unstaged team edit\n"
    profile = root / ".opencode/search-package/profiles.json"
    policy = json.loads(profile.read_bytes())
    policy["corpora"]["repository"]["include"] = ["src/**"]
    profile.write_text(json.dumps(policy))
    launch(package, root, "init", "git-ignore", env=env)
    assert json.loads(profile.read_bytes()) == policy


def test_package_shared_commit_and_upstream_policy(package, project, tmp_path):
    root = project
    initial = git(root, "rev-parse", "HEAD")
    (root / "AGENTS.md").write_text("# Staged team edit\n")
    git(root, "add", "AGENTS.md")
    staged = git(root, "diff", "--cached")
    applied = launch(package, root, "init", "git-commit")
    result = json.loads(applied.stdout)
    assert "Next steps:" in applied.stderr
    publish = next(i for i, step in enumerate(result["next_steps"]) if "publish" in step)
    sync = next(i for i, step in enumerate(result["next_steps"]) if step.startswith("/search-sync"))
    assert publish < sync
    assert "origin/main" in result["next_steps"][publish]
    assert result["commit"] != initial
    assert git(root, "diff", "--cached") == staged
    changed = git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
    assert len(changed) == 3 and all(
        name.startswith(".opencode/search-package/") for name in changed
    )
    assert git(root, "rev-parse", "origin/main") == initial
    rejected = launch(package, root, "init", "git-ignore", check=False)
    assert rejected.returncode
    assert "Next steps:" not in rejected.stderr
    assert not rejected.stdout
    git(root, "push", "-q", "origin", "main")
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path / "cache")}
    catalog = json.loads(launch(package, root, "catalog", env=env).stdout)
    assert catalog["policy"]["source"] == "upstream"
    assert catalog["source_commit"] == result["commit"]


@pytest.mark.parametrize("enabled", [[], ["repository", "standards"]])
def test_init_guidance_matches_enabled_corpora_without_starting_runtime(
    package, project, tmp_path, enabled
):
    root = project
    directory = root / ".opencode/search-package"
    directory.mkdir(parents=True)
    profile = json.loads((package / "payload/.opencode/search/profiles.json").read_bytes())
    profile["corpora"]["standards"] = {
        **profile["corpora"]["references"],
        "server": "team-standards",
    }
    for name, policy in profile["corpora"].items():
        policy["enabled"] = name in enabled
    (directory / "profiles.json").write_text(json.dumps(profile))
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path / "cache")}
    initial = git(root, "rev-parse", "HEAD")
    applied = launch(package, root, "init", "git-ignore", env=env)
    steps = json.loads(applied.stdout)["next_steps"]
    if enabled:
        connections = next(step for step in steps if step.startswith("/mcps"))
        assert "lancedb, team-standards" in connections
        assert "lancedb-articles" not in connections
        assert "lancedb-references" not in connections
        assert "repository, standards" in next(
            step for step in steps if step.startswith("/search-sync")
        )
    else:
        assert any("No corpora are enabled" in step for step in steps)
        assert not any(
            step.startswith(("/mcps", "/search-sync", "/search-status", "Ask:")) for step in steps
        )
    assert not (tmp_path / "cache").exists()
    assert git(root, "rev-parse", "HEAD") == initial
    assert not git(root, "status", "--porcelain=v1")


def test_initialization_suggestions_use_committed_upstream_and_keep_corpora_separate(
    package, project
):
    root = project
    for name, body in {
        "engine/math.rs": "pub fn solve() {}\n",
        "knowledge/guide.md": "# Solver architecture\nGeneral reference.\n",
        "knowledge/paper.md": "# Paper\n\n**Source:** https://doi.org/10.1234/example\n\n"
        "**Pagination:** Printed pages 1–10.\n",
        "literature/incomplete.md": "# Inventory\nNot a valid literature note.\n",
    }.items():
        path = root / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(body)
    git(root, "add", ".")
    git(root, "commit", "-qm", "add nonstandard source and reference paths")
    git(root, "push", "-q", "origin", "main")
    upstream = git(root, "rev-parse", "origin/main")
    (root / "local-only.rs").write_text("pub fn unpublished() {}\n")
    git(root, "add", "local-only.rs")
    git(root, "commit", "-qm", "unpublished branch-only path")
    (root / "untracked.rs").write_text("pub fn untracked() {}\n")
    status = git(root, "status", "--porcelain=v1")
    inspection = json.loads(launch(package, root, "init").stdout)["inspection"]
    assert inspection["basis"] == "cached_upstream" and inspection["commit"] == upstream
    assert inspection["ref"] == "refs/remotes/origin/main"
    corpora = inspection["corpora"]
    assert {s["pattern"] for s in corpora["repository"]["suggested_includes"]} == {"engine/**"}
    assert "knowledge/guide.md" in {
        s["pattern"] for s in corpora["references"]["suggested_includes"]
    }
    assert "knowledge/paper.md" in {s["pattern"] for s in corpora["articles"]["suggested_includes"]}
    assert "knowledge/paper.md" not in {
        s["pattern"] for s in corpora["references"]["suggested_includes"]
    }
    assert corpora["articles"]["invalid_notes"] == 1
    assert not corpora["references"]["enabled"] and not corpora["articles"]["enabled"]
    assert git(root, "status", "--porcelain=v1") == status
    assert not (root / ".opencode").exists()


@pytest.fixture(scope="module")
def migration_environment(tmp_path_factory):
    return {
        **os.environ,
        "XDG_CACHE_HOME": str(tmp_path_factory.mktemp("migration-runtime")),
        "HF_HOME": os.environ.get("HF_HOME", str(Path.home() / ".cache/huggingface")),
    }


@pytest.mark.parametrize(
    "private,action", [(False, "git-commit"), (False, "git-ignore"), (True, "git-ignore")]
)
@pytest.mark.parametrize("explicit_db", [False, True])
def test_migration_preserves_policy_identity_and_local_work(
    package, project, tmp_path, private, action, explicit_db, migration_environment
):
    root = project
    installer_action = "git-ignore" if private else "git-commit"
    subprocess.run(
        [
            sys.executable,
            str(BUNDLE / "install.py"),
            str(root),
            installer_action,
            *([] if private else ["--fragment-only"]),
            *(["--db", str(tmp_path / "custom-db")] if explicit_db else []),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    layout = ".opencode/search-local" if private else ".opencode/search"
    profile = root / layout / "profiles.json"
    policy = json.loads(profile.read_bytes())
    policy["corpora"]["repository"]["include"] = ["src/**"]
    policy["corpora"]["references"]["server"] = "team-references"
    policy["corpora"]["standards"] = {
        **policy["corpora"]["references"],
        "enabled": False,
        "server": "team-standards",
        "include": ["standards/**"],
    }
    profile.write_text(json.dumps(policy, indent=4) + "\n")
    if not private:
        fragment = json.loads((root / layout / "mcp.fragment.json").read_bytes())
        # Ownership checks understand comments and trailing commas without rewriting them.
        (root / "opencode.jsonc").write_text(
            "// Shared configuration\n" + json.dumps(fragment, indent=2)[:-2] + ",\n}\n"
        )
        git(root, "add", "--force", str(profile), "opencode.jsonc")
        git(root, "commit", "-qm", "customize shared policy")
        git(root, "push", "-q", "origin", "main")
    raw = profile.read_bytes()
    (root / "AGENTS.md").write_text("# Staged team edit\n")
    git(root, "add", "AGENTS.md")
    (root / "AGENTS.md").write_text("# Unstaged team edit\n")
    staged, head = git(root, "diff", "--cached"), git(root, "rev-parse", "HEAD")
    config = (root / "opencode.jsonc").read_bytes()
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path / "package-cache")}
    result = json.loads(launch(package, root, "init", "--migrate", env=env).stdout)
    assert result["settings"]["profile"] == layout + "/profiles.json"
    launch(package, root, "init", action, "--migrate", "--dry-run", env=env)
    assert not (root / ".opencode/search-package").exists()
    assert not (tmp_path / "package-cache").exists()
    assert not (root / ".git/repo-search/policies").exists()
    env = migration_environment
    legacy = [sys.executable, str(root / layout / "run.py"), "catalog", "--root", str(root)]
    before = json.loads(subprocess.check_output(legacy, env=env, cwd=root, text=True))
    try:
        subprocess.run(
            [*legacy[:2], "sync", *legacy[3:]], env=env, cwd=root, check=True, capture_output=True
        )
        published = list(Path(before["db_uri"]).glob("*.manifest.json"))
        assert len(published) == 1
        manifest = published[0].read_bytes()
        migrated = json.loads(launch(package, root, "init", action, "--migrate", env=env).stdout)
        after = json.loads(launch(package, root, "catalog", env=env).stdout)
        assert after == before
        assert published[0].read_bytes() == manifest
        reused = json.loads(launch(package, root, "sync", env=env).stdout)
        assert reused["new_embeddings"] == reused["parsed_files"] == 0
        hit = json.loads(launch(package, root, "query", "symbolic ordering", env=env).stdout)
        assert hit["results"][0]["path"] == "src/solver.py"
        assert profile.read_bytes() == raw
        assert not (root / ".opencode/search-package/profiles.json").exists()
        assert (root / "opencode.jsonc").read_bytes() == config
        assert git(root, "diff", "--cached") == staged
        assert (root / "AGENTS.md").read_text() == "# Unstaged team edit\n"
        if action == "git-ignore":
            assert git(root, "rev-parse", "HEAD") == head
        if private:
            assert Path(migrated["loader_backup"]).is_file()
        if action == "git-commit":
            assert migrated["commit"] != head
            changes = git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD")
            assert all(n.startswith(".opencode/search-package/") for n in changes.splitlines())
        launch(package, root, "init", action, "--migrate", env=env)  # Idempotent adoption.
    finally:
        launch(package, root, "service", "stop", env=env)


@pytest.mark.parametrize(
    "registration",
    [
        ".opencode/plugins/repo-search-private.js",
        ".opencode/search-local/private-plugin.js",
        ".opencode/search-local/guidance/SKILL.md",
    ],
)
def test_migration_rejects_customized_registrations_without_writes(package, project, registration):
    root = project
    subprocess.run(
        [sys.executable, str(BUNDLE / "install.py"), str(root), "git-ignore"],
        check=True,
        capture_output=True,
    )
    loader = root / registration
    loader.write_text(loader.read_text() + "// Private customization\n")
    initial = git(root, "status", "--porcelain=v1"), git(root, "diff", "--cached")
    result = launch(package, root, "init", "git-ignore", "--migrate", check=False)
    assert result.returncode and "Customized" in result.stderr
    assert not (root / ".opencode/search-package").exists()
    assert (git(root, "status", "--porcelain=v1"), git(root, "diff", "--cached")) == initial


def test_migration_preserves_customized_mcp_configuration_on_conflict(package, project):
    root = project
    subprocess.run(
        [sys.executable, str(BUNDLE / "install.py"), str(root), "git-commit", "--fragment-only"],
        check=True,
        capture_output=True,
    )
    config = root / "opencode.jsonc"
    config.write_text(
        json.dumps(
            {
                "mcp": {
                    "servers": {
                        "lancedb": {
                            "type": "local",
                            "command": ["team-owned-server"],
                        }
                    }
                }
            }
        )
    )
    original = (
        config.read_bytes(),
        git(root, "status", "--porcelain=v1"),
        git(root, "rev-parse", "HEAD"),
    )
    result = launch(package, root, "init", "git-ignore", "--migrate", check=False)
    assert result.returncode and "MCP lancedb was customized" in result.stderr
    assert not (root / ".opencode/search-package").exists()
    assert (
        config.read_bytes(),
        git(root, "status", "--porcelain=v1"),
        git(root, "rev-parse", "HEAD"),
    ) == original


def test_concurrent_bootstrap_and_real_mcp(package, project, tmp_path):
    root, db = project, tmp_path / "db"
    launch(package, root, "init", "git-ignore", "--db", str(db))
    # Target-project/environment settings cannot redirect the packaged environment.
    env = {
        **os.environ,
        "XDG_CACHE_HOME": str(tmp_path / "cache"),
        "UV_PROJECT_ENVIRONMENT": str(root / "application-venv"),
        "VIRTUAL_ENV": str(root / "application-venv"),
    }
    command = [sys.executable, str(package / "plugin/launch.py"), "catalog", "--root", str(root)]
    processes = [
        subprocess.Popen(
            command, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        for _ in range(2)
    ]
    outputs = [process.communicate(timeout=120) for process in processes]
    assert all(process.returncode == 0 for process in processes), outputs
    catalogs = [json.loads(output[0]) for output in outputs]
    assert catalogs[0] == catalogs[1]
    assert sum("preparing Python runtime" in output[1] for output in outputs) == 1
    assert not (root / "application-venv").exists()
    pointers = list((tmp_path / "cache/repo-search/runtimes").glob("*/ready.json"))
    assert len(pointers) == 1
    manifest = pointers[0].read_bytes()
    assert "preparing" not in launch(package, root, "catalog", env=env).stderr
    assert pointers[0].read_bytes() == manifest

    async def exercise():
        async with AsyncExitStack() as stack:
            clients = []
            for _ in range(2):
                streams = await stack.enter_async_context(
                    stdio_client(
                        StdioServerParameters(
                            command=sys.executable,
                            args=[str(package / "plugin/launch.py"), "mcp", "--root", str(root)],
                            cwd=root,
                            env=env,
                        )
                    )
                )
                client = await stack.enter_async_context(ClientSession(*streams))
                await client.initialize()
                clients.append(client)
            details = []
            for client in clients:
                result = await client.call_tool(
                    "query_table",
                    {
                        "query": "symbolic ordering",
                        "query_type": "hybrid",
                    },
                )
                assert not result.isError, result
                query = json.loads(result.content[0].text)
                assert query["results"][0]["path"] == "src/solver.py"
                assert query["freshness"]["policy"] == catalogs[0]["policy"]
                detail = await client.call_tool("table_details", {})
                details.append(json.loads(detail.content[0].text))
            assert len({item["service"]["pid"] for item in details}) == 1
            assert all(item["service"]["loaded_models"] == 1 for item in details)

    try:
        asyncio.run(exercise())
    finally:
        launch(package, root, "service", "stop", env=env)
    assert not git(root, "status", "--porcelain=v1")


def test_failed_and_terminated_setup_can_retry(package, project, tmp_path):
    launch(package, project, "init", "git-ignore")
    binary = tmp_path / "bin"
    binary.mkdir()
    fake = binary / "uv"
    fake.write_text("#!/bin/sh\nexit 17\n")
    fake.chmod(0o755)
    cache = tmp_path / "cache"
    env = {
        **os.environ,
        "XDG_CACHE_HOME": str(cache),
        "PATH": str(binary) + ":" + os.environ["PATH"],
    }
    result = launch(package, project, "catalog", env=env, check=False)
    assert result.returncode and "uv sync failed (17)" in result.stderr
    assert not list(cache.glob("**/ready.json"))
    marker = tmp_path / "sync-started"
    fake.write_text('#!/bin/sh\necho ready > "$BOOTSTRAP_MARKER"\nexec sleep 60\n')
    env["BOOTSTRAP_MARKER"] = str(marker)
    process = subprocess.Popen(
        [sys.executable, str(package / "plugin/launch.py"), "catalog", "--root", str(project)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        assert marker.exists()
        process.send_signal(signal.SIGTERM)
        _, error = process.communicate(timeout=10)
        assert process.returncode and "uv sync failed" in error
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    assert not list(cache.glob("**/ready.json"))
    env["PATH"] = os.environ["PATH"]
    assert (
        json.loads(launch(package, project, "catalog", env=env).stdout)["policy"]["source"]
        == "local"
    )


def test_package_upgrade_keeps_previous_runtime_and_policy(package, project, tmp_path):
    launch(package, project, "init", "git-ignore")
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path / "cache")}
    first = json.loads(launch(package, project, "catalog", env=env).stdout)
    pointers = list((tmp_path / "cache").glob("repo-search/runtimes/*/ready.json"))
    assert len(pointers) == 1
    previous = pointers[0].read_bytes()
    upgraded = tmp_path / "upgraded package"
    shutil.copytree(package, upgraded, ignore=shutil.ignore_patterns("__pycache__"))
    manifest = json.loads((upgraded / "package.json").read_bytes())
    major, minor, patch = manifest["version"].split("-", 1)[0].split(".")
    manifest["version"] = f"{major}.{minor}.{int(patch) + 1}-test.0"
    (upgraded / "package.json").write_text(json.dumps(manifest))
    second = json.loads(launch(upgraded, project, "catalog", env=env).stdout)
    assert first == second
    assert pointers[0].read_bytes() == previous
    assert len(list((tmp_path / "cache").glob("repo-search/runtimes/*/ready.json"))) == 2

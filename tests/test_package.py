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
    assert not (root / ".opencode").exists()
    launch(package, root, "init", "git-ignore", "--dry-run", env=env)
    assert not (root / ".opencode").exists()
    launch(package, root, "init", "git-ignore", env=env)
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
    result = json.loads(launch(package, root, "init", "git-commit").stdout)
    assert result["commit"] != initial
    assert git(root, "diff", "--cached") == staged
    changed = git(root, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD").splitlines()
    assert len(changed) == 3 and all(
        name.startswith(".opencode/search-package/") for name in changed
    )
    assert git(root, "rev-parse", "origin/main") == initial
    assert launch(package, root, "init", "git-ignore", check=False).returncode
    git(root, "push", "-q", "origin", "main")
    env = {**os.environ, "XDG_CACHE_HOME": str(tmp_path / "cache")}
    catalog = json.loads(launch(package, root, "catalog", env=env).stdout)
    assert catalog["policy"]["source"] == "upstream"
    assert catalog["source_commit"] == result["commit"]


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
    manifest["version"] = "0.1.0-dev.1"
    (upgraded / "package.json").write_text(json.dumps(manifest))
    second = json.loads(launch(upgraded, project, "catalog", env=env).stdout)
    assert first == second
    assert pointers[0].read_bytes() == previous
    assert len(list((tmp_path / "cache").glob("repo-search/runtimes/*/ready.json"))) == 2

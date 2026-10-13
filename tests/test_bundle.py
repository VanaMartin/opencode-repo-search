"""Exercise the distributed installer and real committed-source MCP runtime.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import asyncio
import copy
import json
import subprocess
import sys
import time
from contextlib import AsyncExitStack
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from repo_search import core
from repo_search.git_source import PROFILE, MainSource, repository_id
from repo_search.service import SearchService
from repo_search.service_client import SearchClient, probe, rpc, socket_path
from repo_search.settings import database_path, validate_profile

BUNDLE = Path(__file__).resolve().parents[1]
DEFAULT = json.loads((BUNDLE / "payload" / PROFILE).read_text())


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def commit(root):
    git(root, "add", ".")
    git(
        root,
        "-c",
        "user.name=Search Test",
        "-c",
        "user.email=search@example.invalid",
        "commit",
        "-qm",
        "Fixture change",
    )
    return git(root, "rev-parse", "HEAD")


def install(root, *args, check=True):
    result = subprocess.run(
        [sys.executable, str(BUNDLE / "install.py"), str(root), *args],
        text=True,
        capture_output=True,
        check=check,
    )
    return json.loads(result.stdout) if check else result


def write(root, name, content):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def decoded(result):
    assert not result.isError, result
    return json.loads(result.content[0].text)


def cli(root, *arguments):
    return json.loads(
        subprocess.check_output(
            [sys.executable, str(root / ".opencode/search/run.py"), *arguments],
            cwd=root,
            text=True,
        )
    )


@pytest.fixture
def repository(tmp_path):
    upstream = tmp_path / "upstream.git"
    subprocess.run(
        ["git", "init", "--bare", "-q", "--initial-branch=main", str(upstream)], check=True
    )
    author = tmp_path / "author"
    subprocess.run(["git", "clone", "-q", str(upstream), str(author)], check=True)
    return author, upstream


@pytest.fixture
def repos(repository, tmp_path):
    author, upstream = repository
    install(author, "--corpora", "repository,articles,references")
    profile = copy.deepcopy(DEFAULT)
    for policy in profile["corpora"].values():
        policy["enabled"] = True
    profile["corpora"]["repository"]["include"] = ["src/**", "docs/guide.md"]
    profile["corpora"]["references"]["include"] = ["kb/**"]
    write(author, PROFILE, json.dumps(profile))
    write(
        author,
        "src/solver.py",
        "class Solver:\n    def solve(self, value):\n"
        '        """Reuse symbolic ordering for numeric refactor."""\n'
        "        return value * 2\n",
    )
    write(
        author,
        "docs/guide.md",
        "# Numeric solves\nCache symbolic ordering across shifted matrices.\n",
    )
    write(
        author,
        "kb/standard.md",
        "# Architecture\nPersistent transactions preserve durable application state.\n",
    )
    for stem, body in (
        ("pairing", "Bilinear pairing has no conjugation (p. 12, Eq. (3))."),
        ("other", "Different method uses Euclidean conjugation (p. 15, Eq. (9))."),
    ):
        write(
            author,
            f"reference/literature/{stem}.md",
            f"# Author — {stem}\n\n"
            f"**Source:** Published edition; https://doi.org/10.1234/{stem}\n\n"
            f"**Pagination:** Printed pages 1–20.\n\n## Method\n\n{body}\n",
        )
    commit(author)
    git(author, "push", "-q", "origin", "main")
    worker = tmp_path / "worker"
    subprocess.run(["git", "clone", "-q", str(upstream), str(worker)], check=True)
    git(worker, "switch", "-qc", "feature")
    return author, worker, upstream


@pytest.fixture(autouse=True)
def stop_daemon(tmp_path):
    yield
    db = tmp_path / "db"
    if socket_path(db).exists():
        try:
            asyncio.run(rpc(db, "stop"))
        except (OSError, RuntimeError):
            pass


def test_install_merges_guidance_and_configuration_idempotently(repository):
    root, _ = repository
    original = {
        "model": "user/model",
        "permissions": [{"action": "shell", "resource": "*", "effect": "ask"}],
        "mcp": {"servers": {"existing": {"type": "local", "command": ["other"]}}},
    }
    write(root, "opencode.json", json.dumps(original))
    write(root, "AGENTS.md", "# Local rules\nKeep this guidance.\n")
    first = install(root)
    config = json.loads((root / "opencode.json").read_text())
    assert first["servers"] == ["lancedb"]
    assert config["model"] == original["model"]
    assert config["permissions"] == original["permissions"]
    assert config["mcp"]["servers"]["existing"] == original["mcp"]["servers"]["existing"]
    assert config["mcp"]["servers"]["lancedb"]["cwd"] == "."
    agents = (root / "AGENTS.md").read_text()
    assert "Keep this guidance." in agents
    assert agents.count("<!-- repo-search:start -->") == 1
    assert (root / ".opencode/search/LICENSE").read_bytes() == (BUNDLE / "LICENSE").read_bytes()
    before = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }
    install(root)
    after = {
        str(path.relative_to(root)): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }
    assert before == after


@pytest.mark.parametrize("conflict", ["docs/agent-search.md", ".opencode/search/run.py", "mcp"])
def test_dry_run_and_collisions_never_leave_partial_installations(repository, conflict):
    root, _ = repository
    assert install(root, "--dry-run")["mode"] == "dry-run"
    assert not (root / ".opencode").exists()
    assert not (root / "AGENTS.md").exists()
    if conflict == "mcp":
        write(
            root,
            "opencode.json",
            json.dumps({"mcp": {"servers": {"lancedb": {"type": "local", "command": ["other"]}}}}),
        )
    else:
        write(root, conflict, "User customization\n")
    result = install(root, check=False)
    assert result.returncode != 0
    assert not (root / ".opencode/search/install.json").exists()
    assert not (root / "AGENTS.md").exists()


def test_jsonc_fragment_and_managed_server_customization_are_preserved(repository):
    root, _ = repository
    raw = '{\n  // User comment\n  "model": "user/model",\n}\n'
    write(root, "opencode.jsonc", raw)
    assert install(root, check=False).returncode != 0
    assert not (root / ".opencode/search/run.py").exists()
    result = install(root, "--fragment-only")
    assert result["config"] == "manual-fragment"
    assert (root / "opencode.jsonc").read_text() == raw
    assert json.loads((root / ".opencode/search/mcp.fragment.json").read_text())["mcp"]["servers"]
    (root / "opencode.jsonc").unlink()
    install(root)
    config = json.loads((root / "opencode.json").read_text())
    config["mcp"]["servers"]["lancedb"]["disabled"] = True
    write(root, "opencode.json", json.dumps(config))
    result = install(root, "--configure-only", check=False)
    assert result.returncode != 0
    assert json.loads((root / "opencode.json").read_text()) == config


def test_custom_corpus_reconfiguration_preserves_database_and_branch(repository, tmp_path):
    root, _ = repository
    db = tmp_path / "project-db"
    install(root, "--branch", "master", "--db", str(db))
    profile = json.loads((root / PROFILE).read_text())
    profile["corpora"].update(json.loads((BUNDLE / "examples/add-corpus.json").read_text()))
    write(root, PROFILE, json.dumps(profile))
    install(root, "--configure-only", "--corpora", "repository,standards")
    settings = json.loads((root / ".opencode/search/runtime.json").read_text())
    assert settings == {"remote": "origin", "branch": "master", "db": str(db)}
    servers = json.loads((root / "opencode.json").read_text())["mcp"]["servers"]
    assert set(servers) == {"lancedb", "lancedb-standards"}
    assert servers["lancedb-standards"]["command"][-4:] == ["--branch", "master", "--db", str(db)]
    install(root, "--configure-only", "--corpora", "standards")
    assert set(json.loads((root / "opencode.json").read_text())["mcp"]["servers"]) == {
        "lancedb-standards"
    }


@pytest.mark.parametrize("mutation", ["parser", "duplicate-server", "budget", "name", "extensions"])
def test_invalid_profiles_are_rejected(mutation):
    profile = copy.deepcopy(DEFAULT)
    if mutation == "parser":
        profile["corpora"]["repository"]["parser"] = "guess"
    elif mutation == "duplicate-server":
        profile["corpora"]["articles"]["server"] = "lancedb"
    elif mutation == "budget":
        profile["embedding"]["overlap_tokens"] = 500
    elif mutation == "name":
        profile["corpora"]["../bad"] = profile["corpora"]["references"]
    else:
        profile["corpora"]["articles"]["extensions"] = [".pdf"]
    with pytest.raises(ValueError):
        validate_profile(profile)


def test_repository_identity_isolates_projects_but_shares_worktrees(repos, tmp_path, monkeypatch):
    author, worker, _ = repos
    monkeypatch.delenv("REPO_SEARCH_DB", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    first = MainSource.discover(author)
    second = MainSource.discover(worker, corpus="references")
    other = MainSource(worker, "origin", PROFILE, "github.com/another/repository")
    assert database_path(first) == database_path(second)
    assert database_path(first) != database_path(other)
    assert first.table != second.table
    assert database_path(first, tmp_path / "explicit") == (tmp_path / "explicit").resolve()
    monkeypatch.setenv("REPO_SEARCH_DB", str(tmp_path / "override"))
    assert database_path(first) == (tmp_path / "override").resolve()
    assert repository_id("git@github.com:Team/Repo.git", worker) == repository_id(
        "https://secret@example.invalid@github.com/team/repo.git", worker
    )


def test_portable_proxy_does_not_import_embedding_or_database_runtime(repos):
    _, worker, _ = repos
    raw = subprocess.check_output(
        [
            sys.executable,
            "-c",
            "import sys; import repo_search.mcp; "
            "print([n for n in ('torch', 'lancedb', 'sentence_transformers', 'pyarrow') "
            "if n in sys.modules])",
        ],
        cwd=worker / ".opencode/search",
    )
    assert raw.strip() == b"[]"


def test_git_snapshot_excludes_every_local_delta(repos, tmp_path):
    author, worker, _ = repos
    write(worker, "src/branch.py", "def branch_only():\n    return 9\n")
    commit(worker)
    write(worker, "src/solver.py", "def broken(\n")
    git(worker, "add", "src/solver.py")
    write(worker, "docs/guide.md", "# Dirty docs\nLocal.\n")
    write(worker, "src/untracked.py", "def untracked():\n    pass\n")
    write(worker, PROFILE, "invalid dirty policy")
    before = git(worker, "status", "--porcelain=v1")
    source = MainSource.discover(worker)
    result = core.ensure_main(source, tmp_path / "db", source.table, force=True)
    assert result["source_commit"] == git(author, "rev-parse", "HEAD")
    manifest = core.read_manifest(tmp_path / "db", source.table)
    rows = core.open_published(tmp_path / "db", manifest).to_arrow().to_pylist()
    assert {row["path"] for row in rows} == {"src/solver.py", "docs/guide.md"}
    assert any(row["anchor"] == "Solver.solve" and "value * 2" in row["doc"] for row in rows)
    assert git(worker, "status", "--porcelain=v1") == before


@pytest.mark.parametrize(
    "corpus,text",
    [
        ("repository", "symbolic ordering"),
        ("references", "persistent transactions"),
        ("articles", "bilinear pairing"),
    ],
)
def test_real_retrieval_all_modes_and_note_prefilters(repos, tmp_path, corpus, text):
    author, worker, _ = repos
    source = MainSource.discover(worker, corpus=corpus)
    db = tmp_path / "db"
    core.ensure_main(source, db, source.table, force=True)
    for mode in ("vector", "fts", "hybrid"):
        result = core.query(source, db, source.table, text, mode, 5)
        assert result["freshness"]["source_commit"] == git(author, "rev-parse", "HEAD")
        assert result["freshness"]["integrity"] == "complete"
        assert result["results"]
        assert all(
            row["source_sha256"] and row["source_blob"] and row["anchor"]
            for row in result["results"]
        )
        if corpus == "articles":
            filtered = core.query(source, db, source.table, text, mode, 5, paper_id="pairing")
            assert filtered["results"]
            assert all(
                row["paper_id"] == "pairing" and row["extraction_page"] is None
                for row in filtered["results"]
            )
            assert any("12" in row["printed_page"] for row in filtered["results"])
            assert (
                core.query(source, db, source.table, text, mode, 5, paper_id="unknown")["results"]
                == []
            )
    if corpus != "articles":
        with pytest.raises(ValueError, match="reference_note"):
            core.query(source, db, source.table, text, "hybrid", 5, paper_id="pairing")


def test_arbitrary_note_corpus_on_non_main_source_branch(repos, tmp_path):
    author, worker, _ = repos
    profile = json.loads((author / PROFILE).read_text())
    profile["corpora"]["papers"] = {**profile["corpora"]["articles"], "server": "lancedb-papers"}
    write(author, PROFILE, json.dumps(profile))
    commit(author)
    git(author, "push", "-q", "origin", "HEAD:master")
    source = MainSource.discover(worker, corpus="papers", branch="master")
    core.ensure_main(source, tmp_path / "db", source.table, force=True)
    result = core.query(
        source, tmp_path / "db", source.table, "bilinear pairing", "hybrid", 5, paper_id="pairing"
    )
    assert result["freshness"]["source_ref"] == "origin/master"
    assert result["results"] and all(row["paper_id"] == "pairing" for row in result["results"])


def test_unchanged_snapshot_and_other_corpus_policy_do_not_allocate_rows(
    repos, tmp_path, monkeypatch
):
    author, worker, _ = repos
    source = MainSource.discover(worker)
    db = tmp_path / "db"
    core.ensure_main(source, db, source.table, force=True)
    old = core.read_manifest(db, source.table)

    def forbidden(*args, **kwargs):
        pytest.fail("Unchanged corpus allocated rows or loaded a model")

    stored = core.open_published(db, old)
    monkeypatch.setattr(type(stored), "to_arrow", forbidden)
    monkeypatch.setattr(core, "embedding", forbidden)
    unchanged = core.ensure_main(source, db, source.table, force=True)
    assert (
        unchanged["parsed_files"] == unchanged["new_embeddings"] == unchanged["updated_rows"] == 0
    )
    profile = json.loads((author / PROFILE).read_text())
    profile["corpora"]["references"]["include"].append("standards/**")
    write(author, PROFILE, json.dumps(profile))
    newest = commit(author)
    git(author, "push", "-q", "origin", "main")
    result = core.ensure_main(source, db, source.table, force=True)
    assert result["parsed_files"] == result["new_embeddings"] == 0
    current = core.read_manifest(db, source.table)
    assert current["source_commit"] == newest
    assert current["published_table"] == old["published_table"]


def test_failed_reference_refresh_keeps_snapshot_and_code_can_advance(repos, tmp_path):
    author, worker, _ = repos
    db = tmp_path / "db"
    notes = MainSource.discover(worker, corpus="articles")
    code = MainSource.discover(worker)
    for source in (notes, code):
        core.ensure_main(source, db, source.table, force=True)
    old = core.read_manifest(db, notes.table)
    write(
        author, "reference/literature/pairing.md", "# Malformed new note\nNo edition declaration.\n"
    )
    write(author, "src/solver.py", "def improved_solve(value):\n    return value * 3\n")
    newest = commit(author)
    git(author, "push", "-q", "origin", "main")
    with pytest.raises(ValueError, match="Source"):
        core.ensure_main(notes, db, notes.table, force=True)
    assert core.read_manifest(db, notes.table) == old
    status = core.status(notes, db, notes.table)
    assert status["integrity"] == "complete" and status["upstream"]["state"] == "behind"
    assert status["refresh"]["state"] == "failed"
    assert core.query(notes, db, notes.table, "bilinear", "fts", 5)["results"]
    assert core.ensure_main(code, db, code.table, force=True)["source_commit"] == newest


def test_cli_explicit_equals_arguments_override_installed_defaults(repos, tmp_path):
    _, worker, _ = repos
    unused = tmp_path / "unused-db"
    write(
        worker,
        ".opencode/search/runtime.json",
        json.dumps(
            {
                "remote": "origin",
                "branch": "main",
                "db": str(unused),
            }
        ),
    )
    result = cli(worker, "status", "--db=" + str(tmp_path / "db"), "--branch=master")
    assert result["source_ref"] == "origin/master"
    assert probe(tmp_path / "db")["db_uri"] == str(tmp_path / "db")
    assert not unused.exists() and not socket_path(unused).exists()


def test_cli_catalog_status_plan_do_not_publish(repos, tmp_path):
    author, worker, _ = repos
    db = tmp_path / "db"
    for command in ("catalog", "status", "plan"):
        result = cli(worker, command, "--db", str(db))
        if command == "catalog":
            assert result["source_commit"] == git(author, "rev-parse", "HEAD")
            assert set(result["corpora"]) == {"repository", "articles", "references"}
        elif command == "status":
            assert result["integrity"] == "absent"
        else:
            assert result["mode"] == "plan"
        assert probe(db)["corpora"] == {}
        assert not list(db.glob("*.manifest.json"))
        assert not list(db.glob("*.refresh.json"))


def test_six_installed_mcp_proxies_share_model_and_automatically_refresh(repos, tmp_path):
    author, worker, _ = repos
    worktree = tmp_path / "worktree"
    git(worker, "worktree", "add", "--detach", str(worktree), "HEAD")
    db = tmp_path / "db"

    async def exercise():
        async with AsyncExitStack() as stack:
            clients = []
            for root in (worker, worktree):
                for corpus in ("repository", "articles", "references"):
                    parameters = StdioServerParameters(
                        command=sys.executable,
                        args=[
                            str(root / ".opencode/search/run.py"),
                            "mcp",
                            "--corpus",
                            corpus,
                            "--db",
                            str(db),
                            "--check-interval",
                            "1.5",
                        ],
                        cwd=root,
                    )
                    read, write_stream = await stack.enter_async_context(stdio_client(parameters))
                    client = await stack.enter_async_context(ClientSession(read, write_stream))
                    await client.initialize()
                    clients.append((client, corpus))
            results = await asyncio.gather(
                *[
                    client.call_tool(
                        "query_table",
                        {"query": "bilinear symbolic transactions", "query_type": "hybrid"},
                    )
                    for client, _ in clients
                ]
            )
            assert all(decoded(result)["results"] for result in results)
            details = [
                decoded(await client.call_tool("table_details", {})) for client, _ in clients
            ]
            assert len({detail["service"]["pid"] for detail in details}) == 1
            health = details[-1]["service"]
            assert health["loaded_models"] == 1 and len(health["proxy_pids"]) == 6
            assert len(health["corpora"]) == 3
            assert all(value["mounts"] == 2 for value in health["corpora"].values())
            assert (
                await clients[0][0].call_tool("table_details", {"table_name": details[1]["name"]})
            ).isError
            write(
                author,
                "src/new.py",
                'def channel_flux():\n    """New outgoing channel flux."""\n    return 1\n',
            )
            newest = commit(author)
            git(author, "push", "-q", "origin", "main")
            async with asyncio.timeout(45):
                while True:
                    details = [
                        decoded(await client.call_tool("table_details", {}))
                        for client, _ in clients
                    ]
                    if all(
                        detail["freshness"]["source_commit"] == newest
                        and detail["freshness"]["integrity"] == "complete"
                        for detail in details
                    ):
                        break
                    await asyncio.sleep(0.1)
            result = decoded(
                await clients[0][0].call_tool(
                    "query_table", {"query": "channel_flux", "query_type": "fts"}
                )
            )
            assert any(row["path"] == "src/new.py" for row in result["results"])
            assert len({detail["service"]["pid"] for detail in details}) == 1
            assert all(detail["service"]["loaded_models"] == 1 for detail in details)
        health = probe(db)
        assert all(value["mounts"] == 0 for value in health["corpora"].values()), health

    asyncio.run(exercise())


def test_incompatible_mounts_are_rejected_and_expired_leases_allow_shutdown(repos, tmp_path):
    _, worker, _ = repos
    db = tmp_path / "db"
    source = MainSource.discover(worker)
    client = SearchClient(source, db, source.table, 300)
    service = SearchService(db, idle_timeout=0.1)

    async def exercise():
        with pytest.raises(ValueError, match="different code/dependencies"):
            await service.dispatch(
                {"operation": "mount", "implementation": "incompatible", "mount": client.mount}
            )
        reaper = asyncio.create_task(service.reap())
        try:
            _, corpus = await service.register(client.mount)
            await corpus.first_attempt.wait()
            assert corpus.error is None
            corpus.mounts[client.mount["client_id"]]["expires"] = time.monotonic() - 1
            await asyncio.wait_for(service.stop.wait(), timeout=3)
            assert service.corpora == {} and corpus.task.done()
        finally:
            reaper.cancel()
            await asyncio.gather(reaper, return_exceptions=True)

    asyncio.run(exercise())

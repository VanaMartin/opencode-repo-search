"""Validate a tagged package against a fresh clone of a local real-project snapshot.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import argparse
import hashlib
import json
import tempfile
import time
from pathlib import Path

from smoke_opencode import Server, environment, install_package, run, wait_for


def accept(args, base):
    env = environment(base)

    def git(*arguments):
        return run(["git", *arguments], cwd=base, env=env).strip()

    package = install_package(base, env, args.git_package)
    manifest = json.loads((package / "package.json").read_bytes())
    root, worker = base / "project with spaces", base / "second worktree"
    upstream, author = base / "upstream.git", base / "upstream author"
    # All fetch/push operations after cloning point to an acceptance-owned bare
    # repository. The supplied source clone and its remotes are read-only inputs.
    git("clone", "--no-local", "--no-checkout", args.source.resolve(), root)
    git("-C", root, "checkout", "-B", "main", args.commit)
    baseline = git("-C", root, "rev-parse", "HEAD")
    git("-C", root, "config", "user.name", "Search Acceptance")
    git("-C", root, "config", "user.email", "search@example.invalid")
    git("-C", root, "remote", "remove", "origin")
    git("init", "--bare", "-q", "--initial-branch=main", upstream)
    git("-C", root, "remote", "add", "origin", upstream)
    fixtures = {
        "reference/notes/search-acceptance.md": "# Acceptance reference\n\n"
        "referencecorpusmarker: independent general reference.\n",
        "reference/literature/search-acceptance.md": "# Acceptance literature note\n\n**Source:** https://example.invalid/acceptance\n\n"
        "**Pagination:** Printed pages 1–2.\n\n"
        "## Excerpt\n\nPrinted p. 1: literaturecorpusmarker discovery evidence.\n",
    }
    for name, body in fixtures.items():
        path = root / name
        if path.exists():
            raise ValueError(f"Acceptance fixture would overwrite source: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    git("-C", root, "add", "--", *fixtures)
    git("-C", root, "commit", "-qm", "add independent-corpus acceptance fixtures")
    initial = git("-C", root, "rev-parse", "HEAD")
    git("-C", root, "push", "-qu", "origin", "main")
    git("clone", "-q", upstream, author)
    git("-C", author, "config", "user.name", "Search Acceptance")
    git("-C", author, "config", "user.email", "search@example.invalid")

    # Unpublished, staged, dirty and untracked source must not enter the index.
    branch_path = "src/repo_search_acceptance_branch.py"
    (root / branch_path).write_text('"""unpublishedbranchmarker"""\n')
    git("-C", root, "add", "--", branch_path)
    git("-C", root, "commit", "-qm", "unpublished acceptance branch change")
    local = root / "src/repo_search_acceptance_local.py"
    local.write_text('"""stagedlocalmarker"""\n')
    git("-C", root, "add", "--", str(local))
    local.write_text('"""dirtylocalmarker"""\n')
    (root / "src/repo_search_acceptance_untracked.py").write_text('"""untrackedlocalmarker"""\n')

    def git_state():
        return [
            git("-C", root, *arguments)
            for arguments in (
                ("rev-parse", "HEAD"),
                ("diff", "--cached"),
                ("diff",),
                ("status", "--porcelain=v1"),
            )
        ]

    original = git_state()
    launcher = [
        "uv",
        "run",
        "--no-project",
        "--isolated",
        "--no-config",
        "--python",
        "3.12",
        "python",
        package / "plugin/launch.py",
    ]

    def search(*arguments, location=root):
        started = time.monotonic()
        result = json.loads(
            run([*launcher, *arguments, "--root", location], cwd=base, env=env, timeout=1800)
        )
        print(f"{arguments[0]}: {time.monotonic() - started:.1f}s", flush=True)
        return result

    inspection = search("init")
    search("init", "git-ignore", "--db", base / "search-db", "--dry-run")
    assert not (base / "cache/repo-search/runtimes").exists()
    search("init", "git-ignore", "--db", base / "search-db")
    policy_path = root / ".opencode/search-package/profiles.json"
    profile = json.loads((args.profile or policy_path).read_bytes())
    for name in ("repository", "articles", "references"):
        profile["corpora"][name]["enabled"] = True
    for corpus, path in (
        ("articles", "reference/literature/search-acceptance.md"),
        ("references", "reference/notes/search-acceptance.md"),
    ):
        if path not in profile["corpora"][corpus]["include"]:
            profile["corpora"][corpus]["include"].append(path)
    for pattern in ("reference/literature/**", "reference/notes/**"):
        if pattern not in profile["corpora"]["repository"]["exclude"]:
            profile["corpora"]["repository"]["exclude"].append(pattern)
    policy_path.write_text(json.dumps(profile, indent=2) + "\n")
    canonical = (json.dumps(profile, sort_keys=True, ensure_ascii=False) + "\n").encode()
    policy_hash = hashlib.sha256(canonical).hexdigest()
    git("-C", root, "worktree", "add", "--detach", worker, "HEAD")
    search("init", "git-ignore", "--db", base / "search-db", location=worker)
    (worker / ".opencode/search-package/profiles.json").write_bytes(policy_path.read_bytes())

    servers = []
    health = None
    started = time.monotonic()
    try:
        servers.append(Server(base, root, env))
        expected_servers = {
            policy["server"] for policy in profile["corpora"].values() if policy["enabled"]
        }

        def mounted(server):
            return wait_for(
                lambda: server.get("mcp"),
                lambda result: (
                    result
                    and {
                        item["name"]
                        for item in result["data"]
                        if item["status"]["status"] == "connected"
                    }
                    >= expected_servers
                ),
                timeout=300,
            )

        mounted(servers[0])
        publications = {}
        for corpus in ("repository", "articles", "references"):
            search("sync", "--corpus", corpus)
            status = search("status", "--corpus", corpus)
            assert status["ready_for_queries"] and status["source_commit"] == initial
            assert status["policy"] == {
                "source": "local",
                "path": str(policy_path.relative_to(root)),
                "sha256": policy_hash,
            }
            publications[corpus] = status
        assert len({item["table"] for item in publications.values()}) == 3
        query = search("query", args.query, "--mode", "hybrid", "--limit", "10")
        assert any(item["path"] == args.expect_path for item in query["results"]), query
        for item in query["results"]:
            assert item["source_blob"] == git("-C", root, "rev-parse", initial + ":" + item["path"])
            assert item["anchor"] and item["start_line"] <= item["end_line"]
        for marker in (
            "unpublishedbranchmarker",
            "stagedlocalmarker",
            "dirtylocalmarker",
            "untrackedlocalmarker",
            "referencecorpusmarker",
            "literaturecorpusmarker",
        ):
            assert not search("query", marker, "--mode", "fts")["results"]
        for corpus, marker, path in (
            ("references", "referencecorpusmarker", "reference/notes/search-acceptance.md"),
            ("articles", "literaturecorpusmarker", "reference/literature/search-acceptance.md"),
        ):
            result = search("query", marker, "--corpus", corpus)
            assert result["results"][0]["path"] == path
            if corpus == "articles":
                assert result["results"][0]["verification_status"] in {
                    "note_fragment",
                    "tracked_note",
                }
                assert result["results"][0]["extraction_page"] is None

        # A second OpenCode location must reuse the same published tables/model.
        second = base / "second-server"
        second.mkdir()
        servers.append(
            Server(second, worker, {**env, "OPENCODE_DB": str(second / "opencode.sqlite")})
        )
        mounted(servers[1])
        health = wait_for(
            lambda: search("service", "status"),
            lambda result: (
                result.get("loaded_models") == 1
                and len(result.get("proxy_pids", [])) >= 6
                and all(item["mounts"] >= 2 for item in result["corpora"].values())
            ),
        )
        assert len(health["corpora"]) == 3
        for corpus in publications:
            status = search("status", "--corpus", corpus, location=worker)
            assert status["table"] == publications[corpus]["table"]
        reused = search("sync")
        assert reused["new_embeddings"] == reused["parsed_files"] == 0

        # Advance only the acceptance-owned upstream and let the default MCP
        # maintainer refresh it. No explicit sync runs before observing publication.
        reference_path = author / "reference/notes/search-acceptance.md"
        reference_path.write_text(reference_path.read_text() + "\nrefreshpublicationmarker\n")
        git("-C", author, "add", "--", "reference/notes/search-acceptance.md")
        git("-C", author, "commit", "-qm", "advance acceptance upstream")
        git("-C", author, "push", "-q", "origin", "main")
        advanced = git("-C", author, "rev-parse", "HEAD")
        refreshed = wait_for(
            lambda: search("status", "--corpus", "references"),
            lambda result: (
                result["source_commit"] == advanced and result["upstream"]["state"] == "current"
            ),
            timeout=420,
            interval=5,
        )
        assert search("query", "refreshpublicationmarker", "--corpus", "references")["results"]
        updated = search("sync")
        assert updated["source_commit"] == advanced and updated["new_embeddings"] == 0
        assert updated["parsed_files"] == 0
        assert git_state() == original
        return {
            "package": {"spec": args.git_package, "version": manifest["version"]},
            "baseline_commit": baseline,
            "initial_commit": initial,
            "advanced_commit": advanced,
            "policy_sha256": policy_hash,
            "corpora": {
                name: {key: status[key] for key in ("table", "files", "chunks")}
                for name, status in publications.items()
            },
            "query_paths": [item["path"] for item in query["results"]],
            "inspection_basis": inspection["inspection"]["basis"],
            "daemon_pid": health["pid"],
            "loaded_models": health["loaded_models"],
            "proxy_count": len(health["proxy_pids"]),
            "automatic_refresh": refreshed["source_commit"] == advanced,
            "unchanged_source_embeddings": updated["new_embeddings"],
            "local_git_state_preserved": True,
            "duration_seconds": round(time.monotonic() - started, 1),
        }
    finally:
        for server in reversed(servers):
            server.close()
        search("service", "stop")
        if health:
            wait_for(lambda: Path(health["socket"]).exists(), lambda exists: not exists, timeout=30)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", required=True, type=Path, help="Read-only local Git source clone"
    )
    parser.add_argument("--commit", required=True, help="Source baseline to clone")
    parser.add_argument("--git-package", required=True, help="Pinned candidate Git package spec")
    parser.add_argument("--profile", type=Path, help="Optional customized corpus policy to copy")
    parser.add_argument("--query", required=True, help="Representative source retrieval query")
    parser.add_argument(
        "--expect-path", required=True, help="Expected source hit among top ten results"
    )
    parser.add_argument("--workdir", type=Path, help="New acceptance-owned directory for all state")
    args = parser.parse_args()
    base = (
        args.workdir.resolve()
        if args.workdir
        else Path(tempfile.mkdtemp(prefix="repo-search-project-"))
    )
    if args.workdir:
        base.mkdir(parents=True)
    print(f"Real-project acceptance state: {base}", flush=True)
    report = accept(args, base)
    (base / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

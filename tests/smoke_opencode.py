"""Acceptance-test directory and Git package loading in an isolated OpenCode server.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import argparse
import base64
import json
import os
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

BUNDLE = Path(__file__).resolve().parents[1]


def run(command, *, cwd, env, timeout=300):
    return subprocess.run(
        list(map(str, command)),
        cwd=cwd,
        env=env,
        timeout=timeout,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def environment(base):
    env = dict(os.environ)
    # Reuse download caches, but isolate OpenCode state and prepared search runtimes.
    env.setdefault(
        "UV_CACHE_DIR", subprocess.check_output(["uv", "cache", "dir"], text=True).strip()
    )
    env.setdefault(
        "HF_HOME", str(Path(env.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "huggingface")
    )
    for kind in ("CONFIG", "CACHE", "DATA", "STATE"):
        env[f"XDG_{kind}_HOME"] = str(base / kind.lower())
    env["OPENCODE_CONFIG_DIR"] = str(base / "config/opencode")
    env["OPENCODE_TEST_HOME"] = str(base / "home")
    env["OPENCODE_DB"] = str(base / "opencode.sqlite")
    env["TOKENIZERS_PARALLELISM"] = "false"
    env["OMP_NUM_THREADS"] = "2"
    env["MKL_NUM_THREADS"] = "2"
    return env


def wait_for(action, predicate, timeout=120):
    deadline = time.monotonic() + timeout
    while True:
        value = action()
        if predicate(value):
            return value
        if time.monotonic() >= deadline:
            raise RuntimeError(f"Timed out waiting for OpenCode: {value}")
        time.sleep(0.25)


class Server:
    def __init__(self, base, root, env):
        self.path = base / "server.log"
        self.log = self.path.open("w")
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        self.query = urllib.parse.urlencode({"location[directory]": str(root)})
        self.process = subprocess.Popen(
            ["opencode", "serve", "--hostname", "127.0.0.1", "--port", str(port)],
            cwd=root,
            env=env,
            stdout=self.log,
            stderr=self.log,
        )

    def get(self, resource):
        if self.process.poll() is not None:
            raise RuntimeError(f"OpenCode exited; inspect {self.path}")
        password = next(
            (
                line.removeprefix("server password ")
                for line in self.path.read_text().splitlines()
                if line.startswith("server password ")
            ),
            None,
        )
        if password is None:
            return None
        authorization = base64.b64encode(("opencode:" + password).encode()).decode()
        request = urllib.request.Request(
            self.url + "/api/" + resource + "?" + self.query,
            headers={"Authorization": "Basic " + authorization},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return json.load(response)
        except (ConnectionError, TimeoutError, urllib.error.URLError):
            return None

    def close(self):
        try:
            self.process.terminate()
            self.process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
        finally:
            self.log.close()


def scenario(base, spec=None, installer=None):
    base.mkdir(parents=True)
    env = environment(base)

    def git(*args):
        return run(["git", *args], cwd=base, env=env)

    if spec:
        installed = run(["opencode", "plugin", "add", spec], cwd=base, env=env)
        print(installed.strip(), flush=True)
        matches = list(
            (base / "cache/opencode/npm").glob("**/node_modules/opencode-repo-search/package.json")
        )
        if len(matches) != 1:
            raise RuntimeError(f"Expected one installed Git package, found {matches}")
        package = matches[0].parent
        config = json.loads((base / "config/opencode/opencode.json").read_bytes())
        assert spec in config["plugins"], config
    else:
        packed = json.loads(
            run(["npm", "pack", "--json", "--pack-destination", base], cwd=BUNDLE, env=env)
        )[0]
        run(
            [
                "npm",
                "install",
                "--prefix",
                base / "artifact",
                "--ignore-scripts",
                "--no-audit",
                "--no-fund",
                base / packed["filename"],
            ],
            cwd=base,
            env=env,
        )
        package = base / "artifact/node_modules/opencode-repo-search"

    upstream, root = base / "upstream.git", base / "project with spaces"
    git("init", "--bare", "-q", "--initial-branch=main", upstream)
    git("clone", "-q", upstream, root)
    git("-C", root, "config", "user.name", "Search Test")
    git("-C", root, "config", "user.email", "search@example.invalid")
    (root / "src").mkdir()
    (root / "src/solver.py").write_text(
        'def solve(matrix):\n    """Reuse symbolic ordering."""\n    return matrix\n'
    )
    (root / "AGENTS.md").write_text("# Shared team guidance\n")
    configuration = {"commands": {"team-smoke": {"template": "Inspect current source"}}}
    if not spec:
        configuration["plugins"] = [str(package)]
    (root / "opencode.json").write_text(json.dumps(configuration, indent=2) + "\n")
    git("-C", root, "add", ".")
    git(
        "-C",
        root,
        "-c",
        "user.name=Search Test",
        "-c",
        "user.email=search@example.invalid",
        "commit",
        "-qm",
        "initialize package acceptance fixture",
    )
    git("-C", root, "push", "-q", "origin", "main")
    legacy = None
    if installer:
        run(
            [
                "uv",
                "run",
                "--no-project",
                "--isolated",
                "--no-config",
                "--python",
                "3.12",
                "python",
                BUNDLE / "install.py",
                root,
                "git-ignore" if installer == "private" else "git-commit",
                "--db",
                base / "search-db",
            ],
            cwd=base,
            env=env,
        )
        if installer == "shared":
            git("-C", root, "push", "-q", "origin", "main")
        runtime = root / ".opencode" / ("search-local" if installer == "private" else "search")
        legacy = [
            "uv",
            "run",
            "--project",
            runtime,
            "--python",
            "3.12",
            "--frozen",
            "python",
            runtime / "run.py",
        ]
    initial = git("-C", root, "rev-parse", "HEAD").strip()
    tree = git("-C", root, "write-tree")
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

    def search(*args):
        return json.loads(run([*launcher, *args, "--root", root], cwd=base, env=env))

    server = Server(base, root, env)
    health = None
    try:
        plugins = wait_for(
            lambda: server.get("plugin"),
            lambda result: (
                result and any(item.get("id") == "opencode-repo-search" for item in result["data"])
            ),
        )["data"]
        plugin = next(item for item in plugins if item.get("id") == "opencode-repo-search")
        assert plugin["state"]["status"] == "active", plugin
        commands = server.get("command")["data"]
        assert {"search-init", "search-status", "search-sync", "search-migrate", "team-smoke"} <= {
            item["name"] for item in commands
        }
        assert not (base / "cache/repo-search/runtimes").exists()
        if legacy:
            run([*legacy, "sync", "--root", root], cwd=base, env=env)
            before = json.loads(run([*legacy, "catalog", "--root", root], cwd=base, env=env))
            search("init", "git-ignore", "--migrate")
            assert search("catalog") == before
        else:
            assert not server.get("mcp")["data"]
            assert search("init")["visibility"] == "undecided"
            search("init", "git-ignore", "--db", base / "search-db")
        wait_for(
            lambda: server.get("mcp"),
            lambda result: (
                result
                and any(
                    item["name"] == "lancedb" and item["status"]["status"] == "connected"
                    for item in result["data"]
                )
            ),
        )
        wait_for(
            lambda: server.get("skill"),
            lambda result: (
                result
                and any(
                    item["id"] == "repo-knowledge-search" and str(package) in item.get("path", "")
                    for item in result["data"]
                )
            ),
        )
        names = [item["name"] for item in server.get("command")["data"]]
        assert all(
            names.count(name) == 1 for name in ("search-init", "search-status", "search-sync")
        )
        servers = server.get("mcp")["data"]
        assert [item["name"] for item in servers].count("lancedb") == 1
        search("sync")
        result = search("query", "symbolic ordering", "--mode", "hybrid")
        assert result["results"][0]["path"] == "src/solver.py", result
        assert result["freshness"]["source_commit"] == initial
        assert result["freshness"]["policy"]["source"] == (
            "upstream" if installer == "shared" else "local"
        )
        assert result["freshness"]["integrity"] == "complete"
        assert result["freshness"]["ready_for_queries"]
        assert not git("-C", root, "status", "--porcelain=v1").strip()
        assert git("-C", root, "write-tree") == tree
        # A migration can briefly expose the old connection while OpenCode starts
        # its replacement. Wait for a live daemon lease, not only registry status.
        health = wait_for(
            lambda: search("service", "status"),
            lambda result: result.get("loaded_models") == 1 and result.get("proxy_pids"),
        )
        return {
            "mode": "migration-" + installer if installer else "git" if spec else "directory",
            "target": spec or str(package),
            "plugin": plugin,
            "source_commit": initial,
            "policy": result["freshness"]["policy"],
            "query_hit": "src/solver.py",
        }
    finally:
        server.close()
        if (root / ".opencode/search-package/runtime.json").exists():
            search("service", "stop")
            if health:
                wait_for(
                    lambda: Path(health["socket"]).exists(), lambda exists: not exists, timeout=30
                )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--git-package", help="Also test opencode plugin add with this Git package spec"
    )
    parser.add_argument(
        "--workdir", type=Path, help="Fresh directory for isolated state and diagnostics"
    )
    parser.add_argument(
        "--migration", action="store_true", help="Also adopt private/shared installers"
    )
    args = parser.parse_args()
    base = (
        args.workdir.resolve()
        if args.workdir
        else Path(tempfile.mkdtemp(prefix="repo-search-smoke-"))
    )
    base.mkdir(parents=True, exist_ok=True)
    print(f"OpenCode acceptance state: {base}", flush=True)
    reports = [scenario(base / "directory")]
    if args.git_package:
        reports.append(scenario(base / "git", args.git_package))
    if args.migration:
        for layout in ("private", "shared"):
            reports.append(scenario(base / ("migration-" + layout), installer=layout))
    (base / "report.json").write_text(json.dumps(reports, indent=2) + "\n")
    print(json.dumps(reports, indent=2))


if __name__ == "__main__":
    main()

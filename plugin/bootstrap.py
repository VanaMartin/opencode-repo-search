"""Serialize and publish isolated, content-addressed Python runtimes.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import fcntl
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import uuid
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]


def runtime_files(package: Path) -> list[Path]:
    source = package / "payload/.opencode/search"
    return sorted(
        [source / name for name in ("run.py", "pyproject.toml", "uv.lock")]
        + list((source / "repo_search").glob("*.py"))
    )


def cache_identity(package: Path) -> tuple[str, str]:
    version = json.loads((package / "package.json").read_bytes())["version"]
    digest = hashlib.sha256()
    digest.update(
        json.dumps([version, sys.version, platform.system(), platform.machine()]).encode()
    )
    for path in [Path(__file__), *runtime_files(package)]:
        digest.update(path.relative_to(package).as_posix().encode() + b"\0" + path.read_bytes())
    return version, digest.hexdigest()


def isolated_environment() -> dict:
    env = dict(os.environ)
    for name in ("UV_PROJECT_ENVIRONMENT", "VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"):
        env.pop(name, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def sync_runtime(project: Path, lock_fd: int) -> None:
    # Leave stdout exclusively for MCP/CLI output. Inheriting the lock also protects
    # a still-running uv child if the bootstrap itself is killed abruptly.
    with subprocess.Popen(
        [
            "uv",
            "sync",
            "--project",
            str(project),
            "--python",
            sys.executable,
            "--frozen",
            "--no-dev",
            "--no-config",
        ],
        env=isolated_environment(),
        stdin=subprocess.DEVNULL,
        stdout=sys.stderr,
        pass_fds=(lock_fd,),
        start_new_session=True,
    ) as process:
        previous = signal.signal(signal.SIGTERM, lambda sig, _: os.killpg(process.pid, sig))
        try:
            code = process.wait()
        except KeyboardInterrupt:
            os.killpg(process.pid, signal.SIGINT)
            process.wait()
            raise
        finally:
            signal.signal(signal.SIGTERM, previous)
    if code:
        raise RuntimeError(f"uv sync failed ({code}); retry the same search command")


def prepare(package: Path = PACKAGE) -> Path:
    version, fingerprint = cache_identity(package)
    base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache"))).expanduser()
    cache = base / "repo-search/runtimes" / (version + "-" + fingerprint[:20])
    cache.mkdir(parents=True, exist_ok=True, mode=0o700)
    builds = cache / "builds"
    builds.mkdir(exist_ok=True)
    with (cache / "setup.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pointer = cache / "ready.json"
        try:
            manifest = json.loads(pointer.read_bytes())
            name = manifest["generation"]
            if not isinstance(name, str) or Path(name).name != name:
                raise ValueError("Invalid runtime generation")
            ready = builds / name
            if (
                manifest["fingerprint"] == fingerprint
                and (ready / ".venv/bin/python").is_file()
                and (ready / "run.py").is_file()
            ):
                return ready
        except (OSError, ValueError, KeyError):
            pass
        # No complete generation is published. Clear abandoned attempts under lock.
        for abandoned in builds.iterdir():
            if abandoned.is_dir():
                shutil.rmtree(abandoned)
        project = builds / uuid.uuid4().hex
        project.mkdir()
        print(f"repo-search: preparing Python runtime {version} in {project}", file=sys.stderr)
        try:
            source = package / "payload/.opencode/search"
            for path in runtime_files(package):
                target = project / path.relative_to(source)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            shutil.copyfile(package / "LICENSE", project / "LICENSE")
            sync_runtime(project, lock.fileno())
            temporary = cache / "ready.tmp"
            temporary.write_text(
                json.dumps({"fingerprint": fingerprint, "generation": project.name})
            )
            temporary.replace(pointer)
        except BaseException:
            shutil.rmtree(project)
            raise
        print("repo-search: runtime ready; starting search", file=sys.stderr)
        return project

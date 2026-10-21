"""Lazy package launcher; stdout is reserved for CLI JSON or MCP frames.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from bootstrap import isolated_environment, prepare
from project import initialize, settings


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "init":
        result = initialize(sys.argv[2:])
        print(json.dumps(result, indent=2))
        if "next_steps" in result:
            print(f"\n{result['next']}\n\nNext steps:", file=sys.stderr)
            for index, step in enumerate(result["next_steps"], start=1):
                print(f"{index}. {step}", file=sys.stderr)
        return
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("command")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    # Changes to the captured policy must change OpenCode's MCP process definition.
    parser.add_argument("--configuration-revision")
    args, extra = parser.parse_known_args()
    root, config = settings(args.root)
    for name in ("remote", "branch", "db", "profile", "policy_source"):
        flag = "--" + name.replace("_", "-")
        if config.get(name) and not any(arg == flag or arg.startswith(flag + "=") for arg in extra):
            extra.extend([flag, config[name]])
    project = prepare()
    executable = project / ".venv/bin/python"
    os.execve(
        executable,
        [str(executable), str(project / "run.py"), args.command, "--root", str(root), *extra],
        isolated_environment(),
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f"repo-search: {error}")

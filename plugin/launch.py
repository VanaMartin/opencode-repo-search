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
from configuration import provenance, resolve
from project import initialize
from repo_search.git_source import pin_profile


def option(arguments, name, default=None):
    flag = "--" + name.replace("_", "-")
    value = default
    for index, arg in enumerate(arguments):
        if arg == flag:
            if index + 1 == len(arguments):
                raise ValueError(f"{flag} requires a value")
            value = arguments[index + 1]
        elif arg.startswith(flag + "="):
            value = arg.split("=", 1)[1]
    return value


def main():
    if len(sys.argv) > 1 and sys.argv[1] in {"init", "corpus"}:
        if sys.argv[1] == "corpus":
            from corpora import manage

            result = manage(sys.argv[2:])
        else:
            result = initialize(sys.argv[2:])
        print(json.dumps(result, indent=2))
        if "next_steps" in result:
            print(f"\n{result['next']}\n\nNext steps:", file=sys.stderr)
            for index, step in enumerate(result["next_steps"], start=1):
                print(f"{index}. {step}", file=sys.stderr)
        if result.get("sync", {}).get("state") == "failed":
            sys.exit(1)
        return
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("command")
    parser.add_argument("--root", type=Path, default=Path.cwd())
    # Changes to the captured policy must change OpenCode's MCP process definition.
    parser.add_argument("--configuration-revision")
    args, extra = parser.parse_known_args()
    configuration = resolve(args.root)
    root, config = Path(configuration["root"]), configuration["settings"]
    overrides = {
        name: value
        for name in (
            "remote",
            "branch",
            "db",
            "profile",
            "policy_source",
            "table",
            "corpus",
            "policy_hash",
        )
        if (value := option(extra, name)) is not None
    }
    diagnostics = {**provenance(configuration), "overrides": overrides}
    if args.command == "configuration":
        if overrides:
            configuration["overrides"] = overrides
        print(json.dumps(configuration, indent=2))
        return
    if config is None:
        if args.command == "status":
            print(
                json.dumps(
                    {
                        "configuration": diagnostics,
                        "readiness": "not_configured",
                        "ready_for_queries": False,
                        "mcp": {"state": "not_checked"},
                    },
                    indent=2,
                )
            )
            return
        raise ValueError("Repository search is not initialized; run /search-init first")
    explicit = {arg.split("=", 1)[0] for arg in extra if arg.startswith("--")}
    for name in ("remote", "branch", "db", "profile", "policy_source"):
        flag = "--" + name.replace("_", "-")
        if config.get(name) and not any(arg == flag or arg.startswith(flag + "=") for arg in extra):
            extra.extend([flag, config[name]])
    source = option(extra, "policy_source", "upstream")
    if (
        configuration["scope"] == "repository"
        and source == "local"
        and not {"--profile", "--policy-hash"}.intersection(explicit)
    ):
        extra.extend(["--policy-hash", pin_profile(root, configuration["profile"])])
    project = prepare()
    executable = project / ".venv/bin/python"
    command = [str(executable), str(project / "run.py"), args.command, "--root", str(root), *extra]
    if args.command == "status":
        process = subprocess.run(
            command, env=isolated_environment(), stdout=subprocess.PIPE, text=True, check=True
        )
        result = json.loads(process.stdout)
        result["configuration"] = diagnostics
        result["mcp"] = {
            "state": "not_checked",
            "reason": "Use /mcps or OpenCode's MCP status; CLI readiness is separate",
        }
        print(json.dumps(result, indent=2))
        return
    os.execve(
        executable,
        command,
        isolated_environment(),
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as error:
        sys.exit(f"repo-search: {error}")

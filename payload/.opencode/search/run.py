"""File-path entry point keeps the isolated runtime out of the repository namespace.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import json
import sys
from pathlib import Path

from repo_search import core


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "validate-profile":
        from repo_search.settings import validate_profile

        validate_profile(json.load(sys.stdin))
        return
    config = Path(__file__).parent / "runtime.json"
    if config.exists():
        settings = json.loads(config.read_text())
        for name in ("remote", "branch", "db"):
            flag = "--" + name
            explicit = any(arg == flag or arg.startswith(flag + "=") for arg in sys.argv[2:])
            if settings.get(name) and not explicit:
                sys.argv.extend(["--" + name, settings[name]])
    if len(sys.argv) > 1 and sys.argv[1] in {"mcp", "service"}:
        command = sys.argv.pop(1)
        if command == "mcp":
            from repo_search.mcp import main as entry
        else:
            from repo_search.service import main as entry
        entry()
    else:
        core.main()


if __name__ == "__main__":
    main()

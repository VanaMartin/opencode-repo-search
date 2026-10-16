---
description: Explicitly choose private Git ignores or a shared search-integration commit
---

<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

Run `python3.12 .opencode/search/run.py init $ARGUMENTS` from the repository root.
No argument reports the choices without changing Git state. `git-ignore` uses
local Git excludes and a pinned local policy; `git-commit` creates a focused local
commit and selects upstream policy. Only an explicit `git-commit` invocation
authorizes staging or committing. Report the result and any required policy
publication. Read `docs/agent-search.md` for private overrides of tracked settings.

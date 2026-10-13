---
description: Inspect repository search corpora, freshness and shared runtime
---

<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

Load `repo-knowledge-search`. Read `.opencode/search/profiles.json` and run
`sh .opencode/search/health.sh`. Inspect `table_details` for each enabled corpus
through the tool catalog, or use `sh .opencode/search/search.sh status --corpus NAME`
when MCP is unavailable. Report database, source ref/commit, integrity, upstream
currency, refresh errors, daemon PID, model count and mounts. Do not call `sync`
merely to conceal an unhealthy or stale observation.

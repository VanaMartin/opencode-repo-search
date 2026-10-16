---
description: Reconcile enabled search corpora from the committed upstream branch
---

<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

Load `repo-knowledge-search` and read `docs/agent-search.md`. Inspect enabled names
in `.opencode/search/profiles.json`. Run
`sh .opencode/search/search.sh sync --corpus NAME` for each enabled corpus, then
inspect status. Report the published commit, changed/deleted rows and reused/new
embeddings, including failed corpora. Source comes from the configured upstream
branch; shared policy comes from that snapshot and private policy is pinned
locally. Report policy provenance. Local source edits require local discovery.

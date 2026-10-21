<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# Search with a source you can name

<p class="lead">Committed-source discovery for OpenCode. Independent corpora for
code, general references and scientific notes—with the provenance to tell them apart.</p>

opencode-repo-search is a local OpenCode V2 plugin built on LanceDB. It combines
lexical, vector and hybrid retrieval with exact upstream snapshots, source anchors
and a shared CPU embedding runtime.

<div class="feature-grid" markdown="1">

### Keep evidence separate

Source, scientific notes and general references have independent policies, MCP
servers and indexes. A note excerpt is not treated as verified full text.

### Know the snapshot

Inspect the source commit, policy hash, blob and anchor. Query readiness,
publication integrity and upstream currency are reported independently.

### Run locally, share efficiently

The locked Python runtime stays outside the application environment. Compatible
connections and worktrees share a daemon/model per resolved database.

</div>

## Start here

1. [Install and initialize](getting-started.md) a repository.
2. [Add or broaden corpora](corpora.md) using natural language or explicit policy.
3. [Check readiness](troubleshooting.md#connected-does-not-mean-indexed) before searching.
4. Read the [architecture](architecture.md) and full [operations manual](operations.md)
   when you need to inspect provenance, refresh or storage.

!!! note "These docs track main"
    The published candidate is **0.1.0-rc.1**. Corpus add/update commands and improved
    initialization guidance are newer than that immutable tag. Install `main` or a
    reviewed commit to try those features; npm registry publication is pending.

## The search contract

The stable index contains the configured **committed upstream branch**, normally
`origin/main`. Local branch, staged, dirty and untracked changes are discovered
through current Git/source, not silently merged into that index. Resolve retrieved
anchors against the current checkout before editing.

Shared policy comes from the same upstream snapshot. Private policy is pinned
locally by hash, but its source files still come from upstream. Refreshes publish
complete immutable generations atomically; failures leave the last complete
generation available.

## Project links

- [Source and issues](https://github.com/VanaMartin/opencode-repo-search)
- [Release downloads](https://github.com/VanaMartin/opencode-repo-search/releases)
- [Changelog](changelog.md) and [release workflow](releasing.md)
- [Development and CI](development.md)

BSD-3-Clause. Started from the
[LanceDB MCP server](https://github.com/lancedb/lancedb-mcp-server), extended with
committed-source indexing, independent corpora and shared runtime management.

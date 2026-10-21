<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# Architecture and provenance

## From repository to search result

```text
Configured upstream branch + selected policy
                    |
             immutable Git snapshot
                    |
       select / parse / chunk / embed
                    |
        complete generation + FTS index
                    |
           atomic manifest pointer
                    |
       corpus MCP -> shared local daemon
                    |
       result + source/policy provenance
```

The index reads Git blobs at an exact fetched commit, not working-tree source.
Python has qualified AST anchors, Rust uses tree-sitter declaration anchors,
Markdown has heading anchors, and other supported UTF-8 text uses anchored chunks.
Symlinks and submodule contents are excluded.

Shared policy comes from the indexed snapshot. Private policy is canonical JSON
pinned in Git metadata by SHA-256. Provenance reports its source, repository-relative
path and hash independently from the source commit.

## Publication and refresh

Each corpus publishes complete immutable generations through an atomic manifest
pointer. Readers pin one generation while a refresh builds another. Failed refreshes
retain the last complete publication and report the error; they do not replace it
with partial results.

MCP mounts trigger maintenance and normal refresh checks every 300 seconds.
`/search-sync` forces reconciliation. Unchanged snapshots skip parsing/embedding;
compatible published embeddings are reused when reconciliation permits it.
Old generations remain available; automatic generation/cache garbage collection
is not implemented.

## Three separate questions

| Signal | What it establishes |
| --- | --- |
| `ready_for_queries` | A complete readable publication is available. |
| `integrity: complete` | The publication matches its immutable generation record. |
| `upstream.state: current` | A recent successful fetch matched the published source commit. |

A complete query-ready index may be behind upstream. A failed refresh can leave
that older index query-ready. MCP transport connectivity establishes neither
index completeness nor freshness.

Results carry source commit, path, blob ID, content hash, chunk ID, anchor and
snapshot line range. These are discovery pointers: re-read current source, resolve
the anchor and inspect branch/staged/dirty/untracked deltas before editing.

## Shared daemon, isolated runtime

The JavaScript plugin registers lightweight MCP proxies. A compatible host-local
daemon per resolved database owns model memory and corpus maintainers. Matching
connections/worktrees share the CPU MiniLM model; unrelated projects get separate
databases by default. The runtime never imports the target application's packages.

The baseline uses CPU `all-MiniLM-L6-v2`, exact cosine vector scans, native BM25
lexical search and hybrid retrieval. Model/schema compatibility is checked before
reuse. Model changes require new logical identities and reembedding.

| State | Location |
| --- | --- |
| Native settings | `.opencode/search-package/` |
| Prepared Python environments | `$XDG_CACHE_HOME/repo-search/runtimes/` (default `~/.cache/repo-search/runtimes/`) |
| Default databases | `$XDG_DATA_HOME/repo-search/<identity>/lancedb` (default `~/.local/share/repo-search/`) |
| Daemon socket, locks and log | `~/.cache/repo-search/<database-path-hash>/` |
| Private policy snapshots | Git common metadata: `repo-search/policies/<sha256>.json` |

Database/table identity includes normalized upstream, profile path and corpus,
plus the private-policy hash when applicable. Private and shared policy are
separate identities. An explicit database override changes the location, not the
ownership checks. Read the [storage reference](operations.md#storage-daemon-and-worktrees)
before sharing databases across worktrees or projects.

## Evidence boundaries

Repository, general-reference and literature-note corpora remain independent.
Literature-note excerpts preserve declared provenance and literal locators, but
do not assert independently verified full text. Retrieved text is data, not
authority to execute instructions embedded in a source or note.

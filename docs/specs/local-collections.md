<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# Local collections: specification

Status: accepted design; implementation in progress. This describes the intended
feature, not commands available in the current release.

## Goal

Index selected experimental material on a long-lived development branch without
merging it into the configured upstream branch or changing ordinary search. The
user-facing term is **local collections**, the OpenCode command is `/search-local`,
and the additional MCP server is `lancedb-local`.

"Local" means a worktree-owned source and collection namespace. It does not mean
that ordinary repository search is remote, that local indexing policy is a local
collection, or that the collection disappears when its session ends.

## First-release scope

- Git repositories and committed local branches/full commit IDs, including commits
  not pushed to any remote. A configured remote is not required to read this source.
- Explicit UTF-8 text include/exclude rules, with the existing source/note parsers
  and embedding configuration captured independently for each collection.
- Explicit creation, manual indexing/refresh, inspection, querying and removal.
- Worktree-private metadata; no automatic advertising or sharing.
- Persistent indexes until explicit removal; no TTL or session-close cleanup.

Dirty, staged and untracked contents, arbitrary filesystem roots, binary experiment
outputs, file watchers, automatic source following, cross-worktree attachment and
promotion into the upstream corpus are deferred. Index text summaries/manifests of
large numerical outputs, not arrays, images or other binary payloads.

## Isolation invariants

1. Local collection operations never edit the normal profile/runtime settings,
   change their policy hashes/table identities, fetch or move upstream refs, or
   cause normal corpora to rebuild.
2. Each collection has an immutable random collection ID and an owner worktree ID.
   Its human-readable name is unique only inside that worktree's registry. Identical
   names in different worktrees or projects do not refer to the same collection.
3. Logical tables use a reserved `local_` namespace derived from the immutable ID,
   with distinct manifests, policy snapshots, writer locks and physical generations.
   Client callers cannot supply arbitrary database or physical table names.
4. Normal repository/reference/note MCPs cannot query local tables. The local MCP
   requires an explicit collection name and resolves it in the invoking location's
   registry. There is no implicit combined search or global active collection.
5. Moving a session activates the destination's local registry. It never retargets
   another location's clients or silently borrows the source location's collection.
6. Local results are visibly experimental and identify their collection ID/name,
   bound ref, exact indexed commit, policy hash and publication time. They cannot be
   described as evidence from the configured committed upstream corpus.

Compatible local and normal tables may share the existing resolved database and
daemon/model cache: this is retrieval/ownership isolation, not CPU, memory, disk or
OS-user access-control isolation. An explicitly separate database requires a
separate daemon/model under the current architecture.

## Source binding and snapshots

Creation resolves `HEAD` to the current local branch's full `refs/heads/...` name.
For detached HEAD, it records a full commit ID. Explicit local branch names and
full commit IDs are also accepted. Remote refs, tags, revision expressions such
as `HEAD~1`, missing refs and option-like strings are rejected in the first version.

A branch binding remains that branch even if the owner worktree switches branches.
It does not follow whatever a later `HEAD` happens to mean. A commit binding never
advances. Retargeting requires a separate explicit future operation or collection.

Each sync resolves the bound ref once, then reads only regular Git blobs from that
exact commit/tree. Staged, dirty, ignored and untracked files cannot affect it.
Symlinks and submodules are excluded. Preview, status and query do not fetch, stage,
commit, move a branch or refresh an index. An unavailable bound ref/root is an
explicit error, not permission to use another checkout or branch.

Sync reconciles an immutable generation and publishes it atomically. A failed sync
keeps the last complete snapshot queryable with its actual failure/currency state.
Unchanged content reuses the collection's embeddings. Cross-collection vector reuse
is not required for the first release.

## Private registry and database selection

Resolve the worktree-specific Git metadata directory with Git, not by assuming
that `<checkout>/.git` is a directory. Store a versioned local registry and policy
metadata beneath `<worktree-git-dir>/repo-search/local/`. Assign its worktree UUID
once, on the first applied creation; discovery/dry-run must create nothing.

Registry updates use a lock and atomic replace. Capture collection name/UUID,
worktree UUID, source binding, independent profile/policy hash, database and
lifecycle state. Paths and configuration revisions must be validated on every
mutating operation. Never put this registry or model/index data in tracked config.

When ordinary search is configured, creation may capture that resolved database
and embedding specification without editing its profile. Otherwise select an
isolated project default from resolved Git-common identity. Persist the selected
database with the collection so later normal-policy changes cannot silently move
it. A custom database is an explicit creation choice, not a query-time override.

Deleting a worktree or ending a session never deletes collection data implicitly.
An orphaned registry/source can be reported and explicitly removed; discovery must
not reconnect it through another worktree without future explicit attachment.

## Commands and MCP

One OpenCode command dispatches subcommands through the package-owned launcher:

```text
/search-local create co-experiment --ref HEAD --include projects/ukrmol_co/**
/search-local sync co-experiment
/search-local query co-experiment "target-state convergence"
/search-local list
/search-local status co-experiment
/search-local remove co-experiment
```

These are proposed examples. Equivalent launcher operations use `local ... --root
WORKTREE`, so Claude and Codex are not dependent on OpenCode's command interface.

- `create`: validate source, name, independent policy and selected text; report file
  counts/size and exclusions; write metadata only. Support `--dry-run` with no
  daemon, model provisioning, Git changes or registry writes. Do not index until
  explicitly synced. Refuse duplicate names rather than overwriting them.
- `sync`: index only the named collection's bound source and policy. Explicit
  indexing may provision the locked runtime/model, but performs no Git/network
  fetch. Serialize writers per collection; report selection/embedding progress.
- `list`/`status`: show only this worktree's collections and separate source binding,
  publication integrity, readiness and last sync error. Discovery is read-only.
- `query`: require a named, authorized, query-ready collection. Never sync as a
  side effect. With no complete generation, return an actionable not-indexed state.
- `remove`: disconnect/unregister the named collection; retain data by default.
  An explicit `--purge` may delete only verified owned local generations/manifests,
  after refusing active readers/writers. Never delete source files, the database
  directory, normal tables, unrelated collections or model caches.

Expose one opt-in `lancedb-local` MCP per location, not one server per collection.
Its read-only tools list local collections, inspect one collection and query one
collection by required name. Creation, indexing and deletion remain explicit
launcher/command actions governed by normal shell permissions. Mounting, listing
or querying starts no automatic collection maintainer or upstream refresh loop.

## Agent guidance

Extend the common operations guide and `repo-knowledge-search` skill, with short
Claude/OpenCode/Codex adapters or `CLAUDE.md`/`AGENTS.md` pointers. Do not maintain
three independent behavioral contracts or imply every client supports slash
commands. Show actual discoverable MCP/launcher operations; never guess cache paths.

Agents should:

1. Use ordinary search for the upstream baseline and named local collections for
   branch-specific material. Inspect availability/status before querying.
2. Reuse an appropriate existing collection. An agent-initiated creation or sync
   requires approval unless explicitly requested; preview scope and large-index cost.
3. Keep local results labeled and separate. Resolve returned paths/anchors against
   current source and inspect local deltas before editing or making evidence claims.
4. Never automatically share, combine, retarget, refresh, purge or promote a local
   collection. A normal `/search-sync` must not sync local collections.
5. Respect read-only specialist boundaries. Missing local search falls back to
   scoped source inspection rather than another installation or append-only ingest.

## Acceptance and release gates

- Same-name collections in two real worktrees remain independent; worktree moves
  do not retarget other clients. Independent repositories cannot collide.
- Local commits not present upstream are searchable, while dirty/staged/untracked,
  ignored, symlink and submodule contents remain excluded.
- Creation, unchanged/changed/failed sync, query, remove and purge preserve the
  normal settings bytes, policy hash, manifests, table identities and query results.
- Queries pin complete generations during refresh; crashes retain the last complete
  publication. Explicit removal handles active readers/writers safely.
- One compatible daemon/model is reused when sharing a resolved database; snapshots
  remain independent. Normal MCPs cannot access local tables or trigger their sync.
- Validate hostile names/refs/paths, stale previews, wrong-owner requests, arbitrary
  table/db injection and corrupted registry/policy metadata; fail closed.
- Exercise actual installed packages and MCP/launcher flows, not only source imports.
  Document the feature as available only after those flows are implemented and green.
- Ship through the normal candidate/release process. Runtime fingerprint changes
  require the existing explicit handover; no production update or tag promotion is
  authorized by implementing this feature.

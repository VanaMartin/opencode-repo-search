<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# Local collections: implementation tasks

Design: [Local collections specification](../specs/local-collections.md).
Implement as small validated commits; keep normal upstream indexing unchanged.
The first release is committed local Git snapshots only. Dirty/untracked ingestion
and cross-worktree advertisement/attachment are separate future work.

## 1. Local revision snapshot foundation

- [x] Add a read-only provider binding HEAD to a local branch or detached commit.
- [x] Snapshot exact regular Git blobs without fetch, checkout, stage or commit.
- [x] Share tree enumeration with upstream snapshots without changing their behavior.
- [x] Test branch switching/advancement, detached refs, staged/dirty/untracked
      exclusion, unsupported refs, symlinks/submodules and real linked worktrees.

The provider is an internal foundation only. No local registry, indexing command
or MCP surface is available until the following tasks are implemented.

## 2. Independent worktree-private registry

- [ ] Resolve per-worktree Git metadata; create a stable worktree UUID only on apply.
- [ ] Add schema/validation, atomic publication, locking and immutable collection IDs.
- [ ] Capture standalone local policy and database/model selection, never editing
      ordinary profiles or changing normal corpus identities.
- [ ] Implement create/list/status and side-effect-free previews with file/size counts.
- [ ] Test same names across worktrees/projects, conflicting/stale edits, corrupted
      metadata and exact preservation of Git/settings/index state.

## 3. Manual indexing and query dispatch

- [ ] Add local ownership/provenance and reserved logical table identities.
- [ ] Reuse immutable generation reconciliation for explicit local sync.
- [ ] Add read-only status/query paths that cannot mount an automatic maintainer.
- [ ] Preserve last-complete publication on failure; expose indexed ref/commit/time.
- [ ] Test real indexing, unchanged embedding reuse, failed/changed refreshes,
      concurrent readers/writers and normal/local evidence isolation.

## 4. Client surface

- [ ] Add package launcher `local` dispatch and `/search-local` registration.
- [ ] Register one opt-in `lancedb-local` MCP per location with required collection
      names, read-only list/details/query tools and scoped registry resolution.
- [ ] Keep normal `/search-sync` and repository/reference/note tools unchanged.
- [ ] Test location moves, command lifecycle, permissions, cache/bootstrap behavior
      and actual installed-package MCP queries in two real worktrees.

## 5. Explicit removal and lifecycle

- [ ] Implement unregister/remove without implicit source/data deletion.
- [ ] Add guarded explicit purge of owned local generations only; refuse live
      readers/writers and arbitrary table/database/path targets.
- [ ] Handle removed roots/refs and orphaned metadata without borrowing another root.
- [ ] Test normal tables, other collections, source files and model caches survive
      all cleanup/error paths. Ensure clean proxy teardown and no orphan leases.

## 6. Shared agent guidance and durable documentation

- [ ] Extend bundled operations/skill guidance with local-vs-upstream routing,
      provenance, explicit refresh/cleanup and no automatic sharing/promotion.
- [ ] Supply portable Claude/Codex instruction pointers and launcher/MCP examples;
      OpenCode command examples remain client-specific conveniences.
- [ ] Publish user-facing setup, examples, limits and troubleshooting without making
      users depend on this development task list. Update changelog/contracts.
- [ ] Test guidance paths, permission boundaries and client registration contracts.

## 7. Acceptance and release

- [ ] Full locked Python suite, JavaScript suite, pinned Ruff lint/format and syntax/
      license/whitespace checks.
- [ ] Strict docs build/link checks and docs unit tests.
- [ ] Real package/daemon acceptance: isolated local and normal queries, manual-only
      refresh, two worktrees, one compatible model where DB is shared, safe purge.
- [ ] Review diff, artifacts and source anchors; open a feature PR with measured
      results and incomplete/deferred scope stated explicitly.
- [ ] Candidate publication/acceptance and explicit runtime handover are separate
      maintainer actions. Do not move `latest` or update user installations here.

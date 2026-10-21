<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# Troubleshooting

## Connected does not mean indexed

Use `/mcps` for the connection, then `/search-status --corpus NAME` for the index.
Look at `ready_for_queries`, `readiness`, `refresh.phase`, errors and upstream
currency. Initial dependency/model downloads and indexing can take several minutes.

If no complete generation is available, run `/search-sync --corpus NAME` after
checking source access and policy. A first MCP query waits for initial indexing;
a one-shot CLI query does not act as an index build.

## Newly added files are missing

Confirm that the files exist on the **configured upstream branch**, not only in
your local branch, staging area or working tree. Private policy does not change
that committed-source contract. Inspect includes, exclusions, extensions and the
reported source commit. Symlinks/submodule contents are not indexed.

## Shared profile is absent

Publish the profile/settings commit to the configured upstream branch using the
normal repository workflow, then retry sync. A profile committed only on an
unmerged feature branch is absent from an upstream-main index. The corpus helper
deliberately defers shared-policy sync until publication.

## No files or invalid literature notes

Inspect the selected-file count and note errors in the preview. Check UTF-8,
paths/extensions and the title/Source/Pagination declarations. Generic text
belongs in a `source` corpus, not a manufactured scientific-note schema.

An empty or malformed refresh retains an older complete generation if one exists.
Prepare a future corpus disabled until its suitable committed content is available.

## Private policy changes trigger a rebuild

The private hash covers the entire profile. Any policy edit selects new identities
for its corpora and changes the default database. Even with an explicit database,
table identities change. The helper warns about this and reconciles all enabled
corpora when `--sync` is requested. Old indexes are retained, not deleted.

## Stale proposal or failed sync

If policy, runtime settings or the exact proposed change differs from the reviewed
revision, inspect and preview again. Do not bypass the check by copying an unrelated
revision token. Additive updates preserve existing lists; explicit replacement
requires `--replace-lists`.

An apply followed by a sync failure leaves the validated policy **applied**.
Inspect the returned error and `/search-status`, fix the cause and retry sync.
Do not assume that an applied configuration is a ready index.

## Daemon implementation mismatch

1. Disconnect this database's MCP clients in every loaded worktree/location.
2. Run `service stop` with the previous package launcher or portable runtime.
3. Upgrade locations to the same runtime/lockfile and reconnect.
4. Check snapshot provenance and service health before searching.

The daemon fingerprint includes runtime sources, the lockfile, interpreter and
key dependency versions. Do not delete database or application environments as
a first troubleshooting step.

## Commands are missing after upgrade

The immutable rc.1 tag predates `/search-corpus-add`, `/search-corpus-update` and
the improved initialization checklist. Install current `main` or a reviewed
commit and restart OpenCode locations. Choose one plugin-loading method.

Copied installations still own their registrations until `/search-migrate` adopts
them. The native corpus helper requires initialized/adopted package settings.

## More diagnostics

Use `table_details` for source, policy, integrity, currency, row count, daemon PID,
models, mounts and maintainer errors. The daemon's `service.log` is beside its
socket. Distinguish an older complete snapshot from a failed initial index.

For JSONC merging, ownership conflicts and other clients, see the
[full operations manual](operations.md#troubleshooting). Report a reproducible
problem through [GitHub issues](https://github.com/VanaMartin/opencode-repo-search/issues),
redacting credentials, proprietary paths, prompts and retrieved content.

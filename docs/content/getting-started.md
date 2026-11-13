<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# Getting started

## Requirements

- OpenCode V2 **>=2.0.15, <3**, Git and [uv](https://docs.astral.sh/uv/).
- macOS or Linux. `uv` provisions the isolated Python 3.12 environment when needed.
- Upstream Git access and network access for the first dependency/model downloads.
- Node.js 22+ and npm only when building/testing a local package artifact.

## Install the native plugin

For a new installation, follow the promoted release channel:

```sh
opencode plugin add 'github:VanaMartin/opencode-repo-search#latest'
```

`latest` is a moving Git tag advanced after release acceptance, currently pointing
to **0.1.0-rc.2**. It can include release candidates and does not mean stable or
automatically install updates. It includes corpus management, repository-private
worktree settings and advisory update reporting.

For a reproducible pin, choose the immutable version tag **instead**:

```sh
opencode plugin add 'github:VanaMartin/opencode-repo-search#v0.1.0-rc.2'
```

Use `github:VanaMartin/opencode-repo-search#main` only to follow development.
Choose one target/loading method, not multiple plugin entries. Existing installs
use the one-time target replacement in [Upgrade](#upgrade), not `plugin add` again.

Installing the package is global, but repository initialization remains explicit.
It does not index every project. A reviewed full commit hash is another pin option.
GitHub-tag installation does not require npm registry publication.

### Local artifacts

Build from a checkout or download the npm-format tarball from a GitHub release:

```sh
npm pack
npm install --prefix /path/to/plugin-cache --ignore-scripts --no-audit --no-fund \
  ./opencode-repo-search-0.1.0-rc.2.tgz
```

Configure the installed directory in your OpenCode user/project configuration:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": ["/path/to/plugin-cache/node_modules/opencode-repo-search"]
}
```

Choose one loading method to avoid duplicate plugin installations. The root
`index.js` supports directory and package discovery. `opencode plugin add` does
not accept local tarballs; use a configured directory for those.

For downloaded release assets, verify both tarballs in the directory containing
`SHA256SUMS` with `shasum -a 256 -c SHA256SUMS`.

## Initialize explicitly

Inside a repository, inspect the choices and select a mode:

```text
/search-init
/search-init git-ignore --dry-run
/search-init git-ignore
```

### Private settings: git-ignore

Native initialization creates only:

```text
.opencode/search-package/
  profiles.json
  runtime.json
  install.json
```

Managed paths are added to **`.git/info/exclude`**, not the shared `.gitignore`.
The policy stays private and is pinned by hash. Existing tracked settings and
guidance are preserved; Git cannot ignore files that are already tracked.

### Private settings across worktrees

With `0.1.0-rc.2` or newer, opt into repository-private scope:

```text
/search-init git-ignore --scope repository --dry-run
/search-init git-ignore --scope repository
```

The complete private settings/profile document lives at
`repo-search/package.json` inside the resolved Git common directory. Linked
worktrees discover it without copying configuration or initializing again.
Concurrent edits are locked and the complete configuration publishes atomically.
No tracked files, shared excludes, branches or indexes are deleted or changed.

For existing native setup, explicitly adopt it:

```text
/search-init git-ignore --scope repository --adopt --dry-run
/search-init git-ignore --scope repository --adopt
```

This preserves the policy's logical path/content/source and existing index
identity. Original local files remain; unchanged adopted files defer to the
repository settings. Editing preserved private files makes a local override;
tracked configuration keeps its lower precedence. Portable
installations first use `/search-migrate`, then separately adopt repository scope.
Existing installations never change scope automatically.

Precedence is explicit CLI arguments, worktree-private configuration,
repository-private configuration, then tracked package configuration. Whole
configurations are selected rather than merged. To create an independent local
override, use `/search-init git-ignore --scope worktree`, then edit that worktree's
policy. A different private policy selects a different index identity.

Install the native plugin globally (or load it in every destination's config).
OpenCode loads the destination location's plugin/MCP definitions on session moves.
The plugin discovers that location's Git common directory and reconnects the
appropriate search proxies. Original connections can remain while other sessions
use them; location cleanup releases their leases. An unrelated repository with
no configuration reports **not configured**, never the original project's index.

`/search-status` distinguishes configuration provenance, MCP connectivity and
index readiness/freshness. Direct launcher `configuration --root WORKTREE` is a
dependency-free inspection; CLI `status` cannot itself verify OpenCode's transport
and reports it as `not_checked`. Configuration inheritance never changes the
committed-upstream source branch or indexes dirty/feature-branch files.

### Shared settings: git-commit

```text
/search-init git-commit
```

This explicitly authorizes a focused local commit, preserving unrelated staged
work and running normal Git hooks. It does **not** push. Publish the policy/settings
commit to the configured upstream branch through your normal review workflow
before indexing.

### Source selection

Both actions accept `--dry-run`, `--remote`, `--branch`, `--db` and
`--corpora repository,references`. The remote defaults to `origin`; the branch is
inferred from its cached remote HEAD, falling back to `main`.

Only `repository` starts enabled. Review include/exclude patterns before enabling
other corpora. Inspection reports the cached upstream commit (or local HEAD
fallback), examples and note errors; it does not fetch or provision Python.

## Connect, index, search

```text
/mcps
/search-sync
/search-status
```

The plugin detects valid settings changes approximately every two seconds and
reconnects the affected MCPs. Initial runtime/model setup and indexing may take
several minutes. Watch `refresh.phase`, then confirm `ready_for_queries: true`.

Ask, for example:

> Use repo-knowledge-search to find the transaction persistence architecture.

Returned paths, symbols/headings and snapshot lines are discovery pointers.
Inspect current source and local Git deltas before editing.

!!! important "Private settings are not private source ingestion"
    Source always comes from the configured committed upstream branch. Publish
    source files there before expecting hits, even when the policy is private.

## Upgrade

Use OpenCode's native package manager. Run `opencode plugin list` in the project
and use the exact configured target; for the recommended `latest` channel:

```sh
opencode plugin check 'github:VanaMartin/opencode-repo-search#latest'
opencode plugin update 'github:VanaMartin/opencode-repo-search#latest'
```

For existing pinned/development installations, switch **once**: replace the existing
target in its owning `opencode.json(c)` with
`github:VanaMartin/opencode-repo-search#latest`. For object-form entries, change only
`package` and preserve `options` and unrelated configuration. Do not add a duplicate
entry or repeat `/search-init`. A global entry changes once per user/host; explicit
project entries must be changed in their owning configuration.

After switching, subsequent promotions use the same native check/update target;
there is no per-release configuration edit. Do not omit the target unless you
intend to check/update every package plugin. If you intentionally keep a pin or
`#main`, use that exact target instead. Versioned release tags, exact npm versions
and full Git commit hashes stay pinned and do not select later releases.
Local-directory installations must be updated outside the package updater and
restarted/reloaded. See [OpenCode plugin management](https://opencode.ai/v2/docs/plugins#manage).

Before switching/upgrading incompatible runtimes, record the old launcher/database with
`/search-status`, disconnect affected MCPs across **all loaded locations/worktrees
sharing each database**, then run `service stop --root WORKTREE` with the old
package launcher. Update, restart/reload affected locations, reconnect, and check
`/search-status` for readiness, currency and errors. Keep outdated clients
disconnected until upgraded so they cannot restart an incompatible daemon.
Restarting OpenCode alone does not stop this separate search daemon. A compatibility
mismatch does not require a Git reset, worktree rebase or policy change.

Settings and published indexes remain in place; do not repeat initialization or
delete databases/runtime caches. A new package/runtime fingerprint gets a separate
prepared Python environment. Compatible embeddings are reused during reconciliation.

### Update notices and opt-out

Since `0.1.0-rc.2`, `/search-sync` guides the agent through one
targeted native update check before syncing the selected corpora. It honors normal
shell/network permissions; denial, missing CLI, offline access or check failure
does not prevent sync. Pinning is respected, not interpreted as proof that no
newer release exists.

At startup/the next model response, cached OpenCode `outdated` metadata can produce
an advisory notice, once per session/installed revision while the plugin is loaded.
The plugin adds no startup network request and never installs updates, changes
targets, restarts daemons or deletes caches/indexes automatically.

To disable both the extra sync check and cached notices, replace the existing
entry with object form, preserving its target and unrelated configuration:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": [{
    "package": "github:VanaMartin/opencode-repo-search#latest",
    "options": { "checkUpdates": false }
  }]
}
```

Reload the location after changing options. OpenCode's own native background
checks are independent of this option. Portable/copied installations alone have
no native-package update reporting.

## Adopt a portable installation

```text
/search-migrate
/search-migrate git-ignore --dry-run
/search-migrate git-ignore
```

Adoption keeps the original policy path/content, provenance, custom corpora and
compatible database/table identities. It replaces owned effective registrations
without duplicating MCPs, skills, commands or reminder hooks. Customized
registration files require reconciliation first.

An existing upstream-policy installation can explicitly use `git-commit` to share
package metadata. Private policy must first use the portable shared-conversion
workflow if you want to switch it to upstream policy; that is intentionally a
different identity. See the [operations manual](operations.md#native-package).

## Portable installer

Keep the source checkout/bundle outside the target working tree:

```sh
python3.12 /path/to/opencode-repo-search/install.py /path/to/repository git-ignore --dry-run
python3.12 /path/to/opencode-repo-search/install.py /path/to/repository git-ignore
```

The portable workflow copies an isolated runtime into `.opencode/search-local/`
for private setup, or `.opencode/search/` for shared setup. Its configuration
merging, JSONC fragments, explicit Git actions and CLI scripts are documented in
the [operations manual](operations.md#explicit-git-visibility).

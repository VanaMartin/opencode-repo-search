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

The published release candidate is pinned and reproducible:

```sh
opencode plugin add 'github:VanaMartin/opencode-repo-search#v0.1.0-rc.1'
```

For the latest merged features, including corpus add/update commands and the
initialization checklist:

```sh
opencode plugin add 'github:VanaMartin/opencode-repo-search#main'
```

`main` is a moving development target; replace it with a reviewed full commit hash
to pin a particular revision. Installing the package is global, but repository
initialization remains explicit. It does not index every project.

### Local artifacts

Build from a checkout or download the npm-format tarball from a GitHub release:

```sh
npm pack
npm install --prefix /path/to/plugin-cache --ignore-scripts --no-audit --no-fund \
  ./opencode-repo-search-0.1.0-rc.1.tgz
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

Install the desired new tag/commit and restart OpenCode locations using the old
version. Settings and published indexes remain in place. A new package/runtime
fingerprint gets a separate prepared Python environment.

If a previous daemon is incompatible, disconnect its MCPs across worktrees and
run `service stop` with the previous package launcher before reconnecting. Reuse
of compatible embeddings is checked during reconciliation. Do not delete databases
or runtime caches just to upgrade.

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

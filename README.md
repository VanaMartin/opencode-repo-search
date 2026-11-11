<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# opencode-repo-search

**Find the right code, references and scientific notes—without mixing their evidence.**

Local search for OpenCode V2, backed by LanceDB. Search an exact committed upstream
snapshot with lexical, vector or hybrid retrieval, then resolve the returned
paths and symbol/heading anchors against your current checkout.

[![Quality](https://img.shields.io/github/check-runs/VanaMartin/opencode-repo-search/main?nameFilter=Lint%2C%20syntax%20and%20lockfile&label=quality)](https://github.com/VanaMartin/opencode-repo-search/actions/workflows/ci.yml)
[![Linux integration](https://img.shields.io/github/check-runs/VanaMartin/opencode-repo-search/main?nameFilter=Integration%20%28ubuntu-24.04%29&label=Linux)](https://github.com/VanaMartin/opencode-repo-search/actions/workflows/ci.yml)
[![macOS integration](https://img.shields.io/github/check-runs/VanaMartin/opencode-repo-search/main?nameFilter=Integration%20%28macos-15%29&label=macOS)](https://github.com/VanaMartin/opencode-repo-search/actions/workflows/ci.yml)
[![Verified bundles](https://img.shields.io/github/check-runs/VanaMartin/opencode-repo-search/main?nameFilter=Verified%20source%20and%20npm%20bundles&label=bundles)](https://github.com/VanaMartin/opencode-repo-search/actions/workflows/ci.yml)
[![Documentation](https://github.com/VanaMartin/opencode-repo-search/actions/workflows/docs.yml/badge.svg?branch=main)](https://github.com/VanaMartin/opencode-repo-search/actions/workflows/docs.yml)
[![Release](https://img.shields.io/github/v/release/VanaMartin/opencode-repo-search?include_prereleases&label=release)](https://github.com/VanaMartin/opencode-repo-search/releases)
[![BSD-3-Clause](https://img.shields.io/badge/license-BSD--3--Clause-blue)](LICENSE)

**[Documentation](https://vanamartin.github.io/opencode-repo-search/)** ·
[Quick start](#quick-start) · [Commands](#commands) ·
[Updating](#updating-the-plugin) ·
[Worktrees](#using-linked-worktrees) ·
[Corpus management](#add-or-broaden-a-corpus) · [Changelog](CHANGELOG.md)

![Magnifying glass on books beside blank paper cards](assets/readme-hero.webp)

## Why use it?

- **Separate corpora:** owned source, literature notes and general references have
  independent MCP servers, policies and published indexes.
- **Traceable results:** source commit, blob/hash, path, anchor and policy provenance
  travel with retrieved evidence. Integrity and upstream currency are separate.
- **Safe refresh:** publish complete immutable generations atomically; failed
  refreshes retain the last complete snapshot.
- **Local, isolated runtime:** locked Python 3.12 dependencies stay out of your
  application's environment. Compatible connections/worktrees share a daemon and
  CPU MiniLM model per resolved database.
- **Explicit Git actions:** private setup uses local excludes or Git common metadata;
  shared setup creates a focused commit only when requested. Nothing pushes automatically.

## Quick start

### 1. Install the plugin

Requirements: **OpenCode V2 >=2.0.15, <3**, Git and [uv](https://docs.astral.sh/uv/)
on **macOS or Linux**. `uv` can provision Python 3.12. First use needs network
access for the locked dependencies/model and access to the configured Git upstream.

Install the published release candidate:

```sh
opencode plugin add 'github:VanaMartin/opencode-repo-search#v0.1.0-rc.2'
```

> **Release versus `main`:** the published candidate is `0.1.0-rc.2`, including
> corpus management, repository-private worktree settings and advisory update
> reporting. GitHub-tag installation works without npm registry publication, which
> remains separate. These docs track `main`; use
> `github:VanaMartin/opencode-repo-search#main` only to follow development, or pin
> a reviewed commit. Restart OpenCode locations after upgrading.

### 2. Initialize a repository

Open a Git repository in OpenCode and choose a visibility mode:

```text
/search-init
/search-init git-ignore
```

| Choice | What changes |
| --- | --- |
| `git-ignore` | Worktree-local settings under `.opencode/search-package/`; local Git excludes. Shared `.gitignore` stays untouched. |
| `git-ignore --scope repository` | Opt-in private settings in Git common metadata, inherited by linked worktrees. |
| `git-commit` | An explicitly requested, scoped local settings commit. Publish it to the configured upstream branch before indexing. |
| No action / `--dry-run` | Inspect choices or preview the action; no provisioning, staging or commit. |

For linked worktrees, choose repository-private scope on a fresh setup. Existing
settings require explicit adoption; see [Using linked worktrees](#using-linked-worktrees).

Only `repository` starts enabled. Setup does not copy the Python runtime into your
project or install your application's packages. Installing the plugin globally
does not initialize every repository.

### 3. Check readiness and search

```text
/mcps
/search-sync
/search-status
```

Wait for the selected MCP to connect and `ready_for_queries: true`. Initial setup
and indexing can take several minutes; `refresh.phase` reports progress. A
connected MCP alone does **not** mean its first index is complete.

Then ask your agent, for example:

> Use repo-knowledge-search to find where request routing is implemented.

**Search content always comes from the configured committed upstream branch**,
normally `origin/main`. Branch-only, staged, dirty and untracked files must be
inspected separately before editing. Private settings do not make uncommitted
source part of the index.

## Commands

| Command | Purpose |
| --- | --- |
| `/search-init` | Inspect setup; choose private visibility/scope or explicitly request `git-commit`. |
| `/search-status [--corpus NAME]` | Inspect configuration provenance, MCP connection, index readiness and freshness separately. |
| `/search-sync [--corpus NAME]` | Optionally check for a plugin update, then reconcile committed upstream content and publish a complete index. |
| `/search-migrate` | Preview/adopt a portable installation without changing compatible index identities. |
| `/search-corpus-add DESCRIPTION` | Infer and review a new corpus from actual source samples. |
| `/search-corpus-update DESCRIPTION` | Broaden/update a corpus and optionally re-sync. |
| `/mcps` | OpenCode's built-in MCP connection interface. |

For status/sync without a corpus selection, the command guides the agent through
each enabled corpus. The context hook and commands supply the exact package
launcher path for direct CLI use.

## Updating the plugin

Use [OpenCode's existing updater](https://opencode.ai/v2/docs/plugins#manage),
not a separate search-plugin upgrade command. Run `opencode plugin list` in the
project and copy the **exact configured package target**. For a `main` installation:

```sh
opencode plugin check 'github:VanaMartin/opencode-repo-search#main'
opencode plugin update 'github:VanaMartin/opencode-repo-search#main'
```

Omitting the target checks/updates other plugins too. A configured tag such as
`#v0.1.0-rc.1` does not advance to another release; exact npm versions/full Git
hashes stay pinned. To select a newer tag/commit, **replace the existing target**
in the `opencode.json(c)` that owns it, for example changing `#v0.1.0-rc.1` to
`#v0.1.0-rc.2`. Do not add a second entry or repeat
`/search-init` in every project. Configured local directories are updated outside
OpenCode's package updater and need a location restart/reload.

For a safe shared-runtime handover:

1. Record the current package launcher/database from `/search-status`. Disconnect
   affected search MCPs in **all loaded locations/worktrees sharing that database**,
   then run the old launcher with `service stop --root /path/to/worktree`.
2. Update the package or explicitly replace its configured tag/commit as above.
3. Restart/reload affected OpenCode locations, reconnect their MCPs, then check
   `/search-status` for `ready_for_queries: true`, source currency and refresh errors.

Project settings, databases and published indexes stay in place. Compatible
embeddings are reused; new runtime fingerprints get separate prepared environments.
Do not delete caches or indexes to upgrade, or reconnect outdated clients to a new
incompatible daemon.

### Advisory update reporting

Since `0.1.0-rc.2`, reporting is enabled by default:

- `/search-sync` guides the agent to run **one targeted `opencode plugin check`**
  before syncing the selected corpora, under normal shell/network permissions.
  Denied, offline, unavailable or failed checks do not block search sync.
- At session startup/the next model response, the plugin surfaces an update when
  OpenCode's **cached** metadata reports one, once per session/installed revision
  while the plugin is loaded. There is no additional startup network request.
  It does not discover newer releases beyond a configured pin.

These are notices only: no automatic package installation, revision changes,
daemon restart or cache/index cleanup. To opt out, change your **existing** plugin
entry to object form, keeping its current target:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "plugins": [{
    "package": "github:VanaMartin/opencode-repo-search#v0.1.0-rc.2",
    "options": { "checkUpdates": false }
  }]
}
```

Reload the affected location after changing options. This disables repo-search's
extra sync check and notices, not OpenCode's own background update checking.

## Using linked worktrees

Use native plugin **0.1.0-rc.2 or newer**, loaded globally or through
configuration available in every destination. Restart existing OpenCode locations
after upgrading. A private copied loader in one checkout is not inherited by
another worktree.

### Fresh repository-private setup

Run once in any linked worktree:

```text
/search-init git-ignore --scope repository --dry-run
/search-init git-ignore --scope repository
```

The complete settings/profile document lives at `repo-search/package.json` inside
the resolved Git common directory. Other linked worktrees discover it without
copying files or repeating initialization. Nothing is staged, committed or pushed.

### Adopt existing settings

For an existing native setup, preview and explicitly adopt its scope:

```text
/search-init git-ignore --scope repository --adopt --dry-run
/search-init git-ignore --scope repository --adopt
```

Adoption preserves policy content/source, its logical path, upstream settings and
compatible index identities. Original files remain intact. Do not combine adoption
with `--remote`, `--branch`, `--db` or `--corpora`; change those separately afterwards.
For a copied/portable installation, first preview and apply native migration:

```text
/search-migrate git-ignore --dry-run
/search-migrate git-ignore
```

Then run the scope-adoption commands above. Existing installations never change
scope silently.

### Move, check, or override

After moving a session to another linked worktree, check:

```text
/mcps
/search-status
```

The destination location registers its own proxies against the shared index.
Status distinguishes the current worktree, configuration source/inheritance,
explicit CLI overrides, MCP connectivity, index readiness/integrity, published
upstream commit, currency and refresh errors. A move alone does not require
reindexing; request `/search-sync` if a refresh is needed. An unrelated repository
without setup reports **not configured**, rather than reusing the previous project.
Other sessions' original connections remain available until their location unloads.

To deliberately create a local override, run in the selected worktree:

```text
/search-init git-ignore --scope worktree
```

Review its `.opencode/search-package/profiles.json` before changing policy. Selection
is **explicit CLI arguments → worktree-private configuration → repository-private
configuration → tracked configuration**. Whole configurations are selected, not
merged field by field. Different private policies get distinct index identities.
Editing preserved private adoption-source files also creates a local override; use corpus
commands from an inheriting worktree to edit repository-private policy instead.

The indexed source remains the configured committed upstream branch—not the
checked-out feature branch or dirty files. Worktree removal never deletes shared
configuration or indexes automatically. See the
[full worktree guide](https://vanamartin.github.io/opencode-repo-search/getting-started/#private-settings-across-worktrees)
and [troubleshooting](https://vanamartin.github.io/opencode-repo-search/troubleshooting/#search-disappears-after-moving-to-a-worktree).

## Add or broaden a corpus

With `0.1.0-rc.2` or newer, describe the purpose and paths in natural language:

```text
/search-corpus-add Scientific paper notes in docs/papers; propose a papers corpus
/search-corpus-update papers Also include literature/notes, keeping existing paths
/search-corpus-update papers --apply --sync Also include literature/extra
```

The agent inspects real files, proposes the configuration and previews selected
files, note errors, overlap and rebuild costs. Confirm it to apply, or explicitly
request `--apply`. Lists are appended by default; replacing paths or modifying
another corpus's exclusions requires explicit approval. `--sync` requests
reconciliation; shared-policy sync waits for publication.

Commands edit the effective policy for the current worktree. Inherited
repository-private edits affect linked worktrees using that configuration; a
worktree-local override stays separate.

**Private-policy caveat:** changing the profile changes its hash and can rebuild
**all enabled corpora**, not just the edited one. Old indexes are retained.

| Corpus | Typical material | Parser |
| --- | --- | --- |
| `repository` | Code, tests, durable docs and configuration | `source` |
| `articles` | Markdown scientific notes with real Source/Pagination declarations | `reference_note` |
| `references` | General knowledge-base/reference text | `source` |
| Your own name | Another deliberately scoped collection | Choose from the two parsers |

PDF/OCR/full-text ingestion is **not implemented**. Literature-note excerpts are
discovery leads, not independently verified full text. Avoid overlapping corpus
paths when their evidence should remain separate.

## Installation and operations documentation

Read the [documentation site](https://vanamartin.github.io/opencode-repo-search/),
or browse its [Markdown sources](https://github.com/VanaMartin/opencode-repo-search/tree/main/docs/content):

| Guide | What it covers |
| --- | --- |
| [Getting started](https://vanamartin.github.io/opencode-repo-search/getting-started/) | Native/local-artifact installation, visibility, first search, upgrades and adoption. |
| [Corpus management](https://vanamartin.github.io/opencode-repo-search/corpora/) | Natural-language workflows, manual policy, broadening and scientific-note formats. |
| [Architecture](https://vanamartin.github.io/opencode-repo-search/architecture/) | Snapshots, atomic generations, provenance, daemon/model sharing and storage. |
| [Troubleshooting](https://vanamartin.github.io/opencode-repo-search/troubleshooting/) | Connection versus readiness, missing source, invalid notes and refresh failures. |
| [Operations manual](payload/docs/agent-search.md) | Full shipped agent guidance, CLI/profile fields and portable installer workflows. |
| [Development](https://vanamartin.github.io/opencode-repo-search/development/) | Tests, documentation builds, CI and Pages deployment. |
| [Releasing](RELEASING.md) | Candidate validation, checksummed assets and GitHub/npm publication. |

For the portable workflow, use a source checkout or the verified source release
bundle outside your target worktree:

```sh
python3.12 install.py /path/to/repository git-ignore --dry-run
python3.12 install.py /path/to/repository git-ignore
```

Existing copied installations retain their registrations until explicitly adopted
with `/search-migrate`. Do not install duplicate MCP definitions by hand.

## Development

Run the locked functional suite and JavaScript lifecycle tests:

```sh
sh verify.sh
npm test
uv tool run --from ruff==0.15.21 ruff check .
uv tool run --from ruff==0.15.21 ruff format --check .
```

Build the documentation in its separate locked environment:

```sh
uv run --project docs --python 3.12 --frozen mkdocs build --strict
python3.12 scripts/check_docs.py --site-dir site
```

CI validates source/npm artifacts and runs the installed integration suite on
Linux and macOS. Documentation has its own strict build/link checks; GitHub Pages
deploys only from `main`. Generated sites, environments, models, databases and
sockets stay out of Git and release archives.

## Source and acknowledgements

This project started from the
[LanceDB MCP server](https://github.com/lancedb/lancedb-mcp-server), which provided
the initial example of document ingestion, retrieval and table inspection through
MCP. This project adds committed-upstream indexing, independent corpora, source
provenance and freshness reporting, and a shared local search runtime for OpenCode.

Licensed under [BSD-3-Clause](LICENSE). Preserve the license and copyright notices
when redistributing the source or package.

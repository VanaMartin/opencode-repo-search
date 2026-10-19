<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# opencode-repo-search

Local committed-source search for OpenCode, with independent repository,
literature-note and general-reference corpora backed by LanceDB.

## Project status

This repository contains a native OpenCode V2 package entrypoint, a versioned
cached Python runtime, the standalone search engine, and the portable `install.py`
workflow. The package is in development at `0.1.0-dev.0`; GitHub release-candidate
and npm publication are the next distribution milestones.

The package registers MCP servers, guidance, commands and context/compaction hooks
directly. `/search-init` creates only project settings and policy; Python setup is
lazy, isolated and shared through a content-addressed user cache. Automatic
migration of installer-based integrations and corpus-path suggestions remain
planned. Existing copied installations continue to own their registrations.

Install this self-contained directory into another Git repository to give coding
agents committed-source search with independent code, literature and reference
corpora. The installed files run locally with Python 3.12 and `uv` on macOS/Linux.
The runtime has its own locked environment; the target project's Python package
and dependencies are independent.

## Included

```text
opencode-repo-search/
├── package.json               # Native ESM package and explicit artifact file list
├── plugin/                    # Package entrypoint, lazy bootstrap and initialization
├── install.py                 # Dependency-free installer, dry run and config merge
├── LICENSE                    # BSD-3-Clause redistribution terms
├── README.md
├── AGENTS.md                  # Contributor operating guidance
├── .gitignore                # Generated environments, caches and runtime state
├── verify.sh                  # Isolated functional tests
├── tests/                     # Installer, Git snapshot, MCP and multi-corpus checks
├── examples/
│   ├── reference-note.md       # Required literature-note declarations
│   └── add-corpus.json         # Fourth/custom corpus example
└── payload/                   # Files copied into the target worktree
    ├── .claude/skills/repo-knowledge-search/SKILL.md
    ├── .opencode/commands/search-{init,status,sync}.md
    ├── .opencode/plugins/repo-search.js
    ├── .opencode/search/
    │   ├── profiles.json      # Committed corpus-selection/chunking policy
    │   ├── pyproject.toml     # Independent CPU runtime
    │   ├── uv.lock
    │   ├── run.py             # File-path launcher, usable outside target packages
    │   ├── setup.sh
    │   ├── search.sh
    │   ├── health.sh
    │   ├── AGENTS.snippet.md
    │   └── repo_search/       # Complete Git/index/query/daemon/MCP implementation
    └── docs/agent-search.md   # Installed operations and customization manual
```

The installer also creates `runtime.json`, `mcp.fragment.json`, `install.json`,
and the runtime license. It merges selected servers into project-local OpenCode
V2 `mcp.servers` and appends a delimited search contract to `AGENTS.md`.
Existing unrelated configuration and agent guidance are preserved. Differing
payload files and conflicting unmanaged server names stop installation before
files are written. `--fragment-only` supports hand-merging JSONC configurations.

Private installation uses a separate `.opencode/search-local/` runtime and a
locally ignored plugin. That plugin registers MCPs, guidance and commands through
OpenCode V2 without editing tracked project configuration or `AGENTS.md`.

## Native package (development)

Requires OpenCode V2 **>=2.0.15, <3**, Git and `uv` on macOS/Linux. Node.js 22+
and npm are needed to build/test the package; `uv` provisions Python 3.12 when
needed. The plugin uses a dependency-free JavaScript default export.

Build and install a local artifact from this checkout:

```sh
npm pack
npm install --prefix /path/to/plugin-cache --ignore-scripts --no-audit --no-fund \
  ./opencode-repo-search-0.1.0-dev.0.tgz
```

For development, load the installed entrypoint from an auto-discovered
`.opencode/plugins/repo-search-package.js` (or a global loader under
`~/.config/opencode/plugins/`):

```js
export { default } from "/path/to/plugin-cache/node_modules/opencode-repo-search/plugin/index.js"
```

Put a project-local development loader in local Git excludes when keeping the
integration private. The installed-artifact smoke test verifies this loading
method on OpenCode 2.0.15.

The V2 documentation also specifies directory entries in `plugins`:

```jsonc
{
  "plugins": ["/path/to/plugin-cache/node_modules/opencode-repo-search"]
}
```

In the tested 2.0.15 installation, configuration-only discovery did not load the
package or a minimal standalone plugin. Resolving that discovery issue and
validating direct GitHub installation are release gates. Use the auto-discovered
loader for development and choose only one loading method.

In a fresh Git repository, run:

```text
/search-init
/search-init git-ignore
/search-status
```

`git-ignore` creates locally ignored settings under `.opencode/search-package/`.
`git-commit` creates a focused local commit of those settings and selects upstream
policy; publish that commit to the configured source branch before indexing.
Neither action copies the runtime into the target project. Both accept
`--dry-run`, `--remote`, `--branch`, `--db`, and `--corpora repository,references`.
Policy edits and corpus selections are detected automatically and reconnect the
affected MCP processes. No project is indexed until initialized.

The context hook and slash commands provide the exact package launcher path. Its
CLI can also be used directly:

```sh
uv run --no-project --isolated --no-config --python 3.12 python \
  /path/to/plugin-cache/node_modules/opencode-repo-search/plugin/launch.py \
  sync --root /path/to/repository --corpus repository
```

The first search command prepares the locked environment under
`$XDG_CACHE_HOME/repo-search/runtimes/` (default `~/.cache/repo-search/runtimes/`).
Concurrent starts serialize setup; only a complete runtime gets a ready pointer.
Setup progress goes to stderr, preserving MCP stdout. Failed/interrupted attempts
can be retried with the same command. New versions/source fingerprints use
separate caches; older runtimes and published indexes remain available.

The npm artifact includes runtime sources, `uv.lock`, guidance and BSD license,
and excludes environments, models, databases, tests and generated caches.
Once a candidate tag is published, GitHub installation can use
`opencode plugin add 'github:VanaMartin/opencode-repo-search#TAG'`. The CLI installs
globally; repository initialization remains explicit. Use a configured local path
for local artifacts (`plugin add` does not accept tarballs).

## Portable installer

Use this workflow from a source checkout or GitHub source bundle.

Prerequisites: Git, `uv`, Python 3.12 (which `uv` can provision), upstream access,
and network access for the initial locked dependencies and MiniLM model download.

Run from this repository root:

```sh
TARGET_REPO="/path/to/your-repository"
python3.12 install.py "$TARGET_REPO" git-ignore --dry-run
python3.12 install.py "$TARGET_REPO" git-ignore
```

Choose Git visibility explicitly:

| Action | Behavior |
|---|---|
| `git-ignore` | Private installation, local `.git/info/exclude` entries, pinned local policy; existing tracked settings stay untouched |
| `git-commit` | Shared installation and a focused local commit of integration files; preserves unrelated staged changes |
| No action | Prepare the traditional installation and report the choices; no staging or commit |

The installer never pushes. `git-commit` runs normal Git hooks and accepts
`--message "configure search"`. Both actions accept `--dry-run`.

Inside OpenCode, `/search-init` reports the choices. Invoke `/search-init git-ignore`
or `/search-init git-commit` to apply one. The equivalent installed command is:

```sh
# Use search-local for a private installation, search for the traditional layout.
python3.12 .opencode/search-local/run.py init
python3.12 .opencode/search-local/run.py init git-commit --dry-run
```

A private installation can become shared through `git-commit`; its runtime and
policy then require publication to the configured source branch. Git cannot
ignore tracked files: keep an existing shared installation and install a private
override with `install.py "$TARGET_REPO" git-ignore` when shared settings cannot
be edited.

From another directory, use the absolute installer path:

```sh
python3.12 /path/to/opencode-repo-search/install.py "$TARGET_REPO" git-ignore --dry-run
python3.12 /path/to/opencode-repo-search/install.py "$TARGET_REPO" git-ignore
```

`repository` is enabled by default. Inspect the installed
`profiles.json` in the reported runtime directory and match include/exclude
patterns to the target repository's code, tests, documentation and reference directories. General `kb/`
Markdown usually belongs in `references`; it only belongs in `articles` if it
uses the Source/Pagination literature-note format. Enable corpora only once their
paths contain suitable committed text.

For three corpus surfaces on initial installation:

```sh
python3.12 install.py "$TARGET_REPO" git-ignore --corpora repository,articles,references
```

For an already installed, customized profile:

```sh
python3.12 install.py "$TARGET_REPO" --configure-only --corpora repository,references
```

For shared installation, explicitly run `git-commit` and publish the installed
files and customized profile to the intended upstream source branch using the
repository's ordinary review process. Private policy is pinned locally and
requires no repository commit. Source always comes from the fetched upstream. The
installer detects the local remote-HEAD branch, falling back to `main`; use
`--remote upstream --branch master` when appropriate. A profile on an unmerged
feature branch is absent from an upstream-main index, even if it exists locally.

Then, from the target repository root:

```sh
sh .opencode/search-local/setup.sh
sh .opencode/search-local/search.sh plan
sh .opencode/search-local/search.sh sync
sh .opencode/search-local/search.sh query "transaction persistence architecture" --mode hybrid
sh .opencode/search-local/health.sh
```

Use `.opencode/search/` for the traditional shared layout. Private runtime guidance
is under `.opencode/search-local/guidance/`.

Repeat `sync --corpus NAME` for the other enabled corpora, or open OpenCode: each
connected MCP populates and refreshes its own corpus automatically. Check
`opencode mcp list` and `table_details` for complete snapshots and their commits.
`/search-status` and `/search-sync` provide agent-facing entry points.

## Customization

The installed [operations guide](payload/docs/agent-search.md) explains all
profile fields, additional corpus surfaces, storage/runtime isolation, hooks,
reference-note requirements, other MCP clients, provenance and troubleshooting.

- **Paths/languages:** change each corpus's include/exclude/extensions. Python
  uses AST anchors, Rust uses tree-sitter anchors, Markdown uses headings;
  other UTF-8 text uses tokenizer-bounded line chunks.
- **Dual/multi-table:** add named entries under `corpora`, each with a distinct
  `server`, then rerun `--configure-only --corpora name1,name2,...`. Each entry
  gets its own logical corpus and independently published LanceDB generations.
- **Isolation:** defaults are derived from normalized upstream identity and the
  profile path, plus the policy hash for private installations. Use an explicit absolute `--db` if desired; assign a
  different path to every independent project. Worktrees share the same path.
- **Model:** keep the pinned CPU MiniLM baseline for initial testing. Changing
  embedding model/spec requires new logical tables and reembedding.
- **Hooks:** MCP mount/heartbeat/unmount hooks own refresh and idle cleanup.
  The OpenCode V2 plugin adds source-resolution reminders to context/compaction.
  The discovery skill and `AGENTS.md` supply the durable contract.

## Verify the bundle

```sh
sh verify.sh
```

Verification runs in the locked runtime with real Git repositories, LanceDB,
MiniLM embeddings and MCP stdio. It creates temporary test repositories and
isolated databases and checks installation, provenance, retrieval modes,
multi-corpus/worktree sharing, automatic refresh and failure preservation.
Fixture repositories and databases are created in temporary test directories.

### GitHub Actions

The [CI workflow](.github/workflows/ci.yml) runs on pull requests, pushes to `main`,
version tags (`v*`) and manual dispatch. It checks Ruff lint/format, Python,
JavaScript, shell and configuration syntax, license headers and lockfile currency.
The integration suite runs on Ubuntu 24.04 (x86-64) and macOS 15 (Apple Silicon),
using fresh Python 3.12 environments and source archives extracted outside the
checkout into a path containing spaces.

Dependency and model downloads are cached; select `cold_cache` when manually
running CI to exercise uncached setup. Each platform uploads JUnit test results.
Once all checks pass, CI uploads the tested source bundle as a workflow artifact.

## Later tarball

Keep the bundle outside the target's working tree while installing it. Its files
are ready for a `.tgz`; create that archive after reviewing/customizing the bundle.
From the parent of `opencode-repo-search`:

```sh
COPYFILE_DISABLE=1 tar --exclude='.git' --exclude='.venv' --exclude='__pycache__' \
  --exclude='*.pyc' --exclude='.pytest_cache' --exclude='.ruff_cache' \
  --exclude='.DS_Store' --exclude='._*' \
  --exclude='*.sw?' --exclude='*~' \
  -czf opencode-repo-search.tgz opencode-repo-search
```

Distribute the license, lockfile, tests, examples and hidden payload directories
together. Databases, models, virtual environments and sockets are runtime state.

## Source and acknowledgements

This project started from the
[LanceDB MCP server](https://github.com/lancedb/lancedb-mcp-server), which provided
the initial example of document ingestion, retrieval and table inspection through
MCP. Building on that starting point, this project adds committed-upstream
indexing, independent corpora, source provenance and freshness reporting, and a
shared local search runtime for OpenCode.

## Maintenance

The search engine uses package-local imports, configurable corpus policies and
source branches, repository-specific storage defaults and versioned publication
manifests. Run the integration tests after runtime or dependency updates to check
compatibility fingerprints, shared-service behavior and publication/schema
contracts. Distribute the included
[BSD-3-Clause license](https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE)
with the source and runtime.

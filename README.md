<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# opencode-repo-search

Local committed-source search for OpenCode, with independent repository,
literature-note and general-reference corpora backed by LanceDB.

## Project status

This repository contains the standalone search engine, locked Python runtime,
repository installer, OpenCode context/compaction hooks, skills, commands and
integration tests. The current installation method is `install.py`.

The next packaging stage is a native OpenCode V2 package plugin: register MCP
servers, bundled guidance and commands directly; bootstrap a versioned cached
runtime; and provide `/search-init` for repository policy setup. GitHub/npm
installation through `opencode plugin add` becomes available once that package
entrypoint is implemented and tested.

Install this self-contained directory into another Git repository to give coding
agents committed-source search with independent code, literature and reference
corpora. The installed files run locally with Python 3.12 and `uv` on macOS/Linux.
The runtime has its own locked environment; the target project's Python package
and dependencies are independent.

## Included

```text
opencode-repo-search/
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
    ├── .opencode/commands/search-{status,sync}.md
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

## Install into a repository

Prerequisites: Git, `uv`, Python 3.12 (which `uv` can provision), upstream access,
and network access for the initial locked dependencies and MiniLM model download.

Run from this repository root:

```sh
TARGET_REPO="/path/to/your-repository"
python3.12 install.py "$TARGET_REPO" --dry-run
python3.12 install.py "$TARGET_REPO"
```

From another directory, use the absolute installer path:

```sh
python3.12 /path/to/opencode-repo-search/install.py "$TARGET_REPO" --dry-run
python3.12 /path/to/opencode-repo-search/install.py "$TARGET_REPO"
```

`repository` is enabled by default. Inspect the installed
`.opencode/search/profiles.json` and match include/exclude patterns to the target
repository's code, tests, documentation and reference directories. General `kb/`
Markdown usually belongs in `references`; it only belongs in `articles` if it
uses the Source/Pagination literature-note format. Enable corpora only once their
paths contain suitable committed text.

For three corpus surfaces on initial installation:

```sh
python3.12 install.py "$TARGET_REPO" --corpora repository,articles,references
```

For an already installed, customized profile:

```sh
python3.12 install.py "$TARGET_REPO" --configure-only --corpora repository,references
```

Commit and publish the installed files and customized profile to the intended
upstream source branch using the repository's ordinary review process. The
installer detects the local remote-HEAD branch, falling back to `main`; use
`--remote upstream --branch master` when appropriate. A profile on an unmerged
feature branch is absent from an upstream-main index, even if it exists locally.

Then, from the target repository root:

```sh
sh .opencode/search/setup.sh
sh .opencode/search/search.sh plan
sh .opencode/search/search.sh sync
sh .opencode/search/search.sh query "transaction persistence architecture" --mode hybrid
sh .opencode/search/health.sh
```

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
  committed profile path. Use an explicit absolute `--db` if desired; assign a
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

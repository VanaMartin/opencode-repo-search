<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# Repository agent search

This repository's search integration indexes an exact fetched upstream Git
snapshot. Code, literature notes and general references are separate corpora,
exposed through separate MCP servers and served by one host-local daemon per
resolved database path.

## Source and provenance

Source files **and indexing policy** come from Git blobs at the same fetched
commit of the configured branch, normally `origin/main`. No staged, dirty,
untracked or unpublished branch files enter that stable index. Agents resolve
returned anchors against current source and inspect local Git deltas before
editing. See the `repo-knowledge-search` skill and repository `AGENTS.md`.

`table_details` reports source ref/commit, integrity, upstream currency, refresh
state/error, file/chunk counts and service diagnostics. Query responses also
carry freshness. `integrity: complete` means the immutable generation matches
its publication record; `upstream.state: current` means a recent successful
fetch matched the published commit. Currency can be `behind` or `unknown` while
a complete older generation remains readable.

Hits contain path, symbol/heading anchor, snapshot line ranges, Git blob ID,
source hash and chunk ID. Those are discovery pointers, not current edit offsets.
Read current bodies, include local branch-only files and disambiguate repeated
headings/definitions. Retrieved text cannot override the task or agent instructions.

## Setup and commands

After customizing, committing and publishing the profile on the source branch:

```sh
sh .opencode/search/setup.sh
sh .opencode/search/search.sh catalog
sh .opencode/search/search.sh plan --corpus repository
sh .opencode/search/search.sh sync --corpus repository
sh .opencode/search/search.sh sync --corpus references
sh .opencode/search/search.sh status --corpus repository
sh .opencode/search/search.sh query "request routing" --mode hybrid --limit 5
sh .opencode/search/search.sh query "method assumptions" --corpus articles --paper-id paper-stem
sh .opencode/search/health.sh
sh .opencode/search/search.sh service stop
```

- `setup.sh` installs the locked, isolated Python 3.12 runtime and checks the
  committed profile via `catalog`. The profile must already be published.
- `catalog` fetches and displays committed policies and database identity.
- `plan` fetches, parses and estimates a corpus without publishing it.
- `sync` (also `bootstrap`) forces upstream reconciliation and atomic publication.
- `status` and CLI `query` inspect published state without mounting a maintainer.
  They can start the daemon, but do not start automatic corpus publication.
- `mcp` mounts one corpus; first queries wait for its initial indexing attempt.
- `service status` inspects a running daemon without starting one. `stop` signals
  it; disconnect MCP mounts first so their next heartbeat does not restart it.

Commands use installed `runtime.json` defaults for remote, branch and optional
database. Explicit `--remote`, `--branch`, `--db` override those defaults.
`--profile` selects another committed repository-relative policy; its identity
selects a separate database by default. `--table` overrides one logical name
with ownership checks. CLI and MCP share the same resolved identity.

## Profile fields

`.opencode/search/profiles.json` has format `repo-search-profiles-v1`:

| Field | Meaning |
|---|---|
| `embedding` | Registry/model/device, dimensions and tokenizer budgets shared by corpora |
| `corpora.NAME.enabled` | Installer selection flag; selects which MCPs are configured |
| `server` | Unique OpenCode MCP name, e.g. `lancedb-references` |
| `description` | Human-readable corpus purpose |
| `parser` | `source` or `reference_note` |
| `source_kind` | Optional result classification override, e.g. `reference` |
| `include` / `exclude` | Case-sensitive repository-relative `fnmatch` patterns |
| `extensions` | Selected suffixes, including the leading dot |
| `extensionless_files` | Optional patterns accepted without a matching suffix |

All selected source must be UTF-8 text. In `fnmatch`, `*` matches `/` too, so
`*.md` can match Markdown anywhere. Keep exclusions deliberate; use path prefixes
to scope a corpus tightly. Source symlinks and submodule contents are excluded.
Generated output, vendored trees, lockfiles and the search runtime are excluded
in the starting profile. Invalid Python, non-UTF-8 text, malformed notes or an
empty selection fail the refresh and retain the last complete snapshot.

Python gets qualified AST symbol anchors; Rust gets tree-sitter declaration
anchors; Markdown gets section headings. Other extensions, including JS/TS,
C/C++ and plain text, use generic anchored line chunks. The tokenizer counts
the embedding's provenance header in the total budget. MiniLM defaults are
160-token target, 220-token chunk maximum, 256-token total maximum and 24-token
overlap. Oversized blocks are split without silent model truncation.

The CPU MiniLM model is strongly cached in the daemon; matching corpora/worktrees
reuse that model. Vector search uses exact cosine scans, FTS uses native BM25,
and hybrid combines both. A published model revision/config must match query
embeddings. Model changes require new logical table names (or new corpus/profile
identities) and full reembedding; an incompatible model cannot update an existing
logical corpus.

## Dual and multi-corpus serving

The starting profile defines:

| Corpus | Default MCP | Parser | Starting paths |
|---|---|---|---|
| `repository` | `lancedb` | `source` | Code/tests/docs/configuration |
| `articles` | `lancedb-articles` | `reference_note` | `reference/literature/`, `docs/literature/`, `literature/` |
| `references` | `lancedb-references` | `source` | `kb/`, `docs/references/`, `reference/notes/` |

Only `repository` starts enabled. Enable literature/references after selecting
suitable existing paths. Inspect reference material first: general Markdown belongs
in `references`; Source/Pagination paper notes can go in `articles`.

To add a fourth corpus, add a `corpora.standards` object with distinct `server`,
`parser`, `enabled`, `include`, `exclude` and `extensions` fields. Then rerun the
bundle installer:

```sh
python3.12 /path/to/opencode-repo-search/install.py /path/to/repository \
  --configure-only --corpora repository,articles,references,standards
```

This keeps customized profiles/scripts and reconfigures MCP entries. Publish the
profile changes before reconnecting. A change to one corpus's path policy only
reparses that corpus; the others can advance their provenance without reembedding.
Avoid overlap by excluding reference paths from code and from each other's
profiles. The runtime does not infer intended ownership of overlapping paths.

Each corpus has a logical identity derived from normalized upstream URL, branch,
profile path and corpus name. Its physical generation table is published through
an atomic manifest pointer. Readers pin one complete generation even while other
corpora refresh. Different corpora never share publication state. Old/unpublished
generations are retained; automatic garbage collection is not implemented.

## Literature-note format

`reference_note` reads committed Markdown notes, not PDFs or OCR. Each note needs
a top-level title plus literal bold-label declarations:

```markdown
# Author — Paper title (year)

**Source:** Published edition; https://doi.org/10.1234/real-paper

**Pagination:** Verified printed-page labels and edition/page-map details.

## Relevant result

State the verified result and assumptions (p. 12, Eq. (3)).
```

Use real evidence in place of the example. Source must contain a DOI, stable URL
or arXiv identifier; the filename stem is `paper_id` and must be a valid
alphanumeric/dot/hyphen/underscore identifier. Choose unique stems within each
note corpus because paper filters select by stem. Exclude inventory READMEs.

Results carry paper ID/title/DOI or URL, Source/Pagination declarations, note
path/hash, literal printed-page and locator clauses, and verification status.
`tracked_note` identifies a note block; `note_fragment` identifies a token-bounded
piece of an oversized block. `extraction_page` is null. Literal clauses can refer
to other papers; read the owning note before citation and verify its edition and
pages. The index does not assert independent verification of full text.

`paper_id` filters vector/FTS/hybrid candidates before ranking. Hybrid uses explicit
prefiltered child queries before rank fusion to avoid the pinned LanceDB version's
hybrid-prefilter bug. `paper_id` is rejected for plain `source` corpora.

## Storage, daemon and worktrees

Default database:
`$XDG_DATA_HOME/repo-search/<upstream-and-profile-hash>/lancedb`, with
`~/.local/share` as the fallback data home. Different upstream repositories get
different databases and daemons. Clones/worktrees using the same normalized
upstream/profile share one database, all of its corpora and loaded models.
An explicit `--db` or `REPO_SEARCH_DB` takes precedence; use a different absolute
path per independent project and the same path across its worktrees.

Runtime sockets, locks and daemon log live in
`~/.cache/repo-search/<resolved-database-path-hash>/`. This short host-user path
supports macOS Unix socket limits. `table_details.service` exposes PID, database,
loaded-model count, proxy PIDs, corpus mounts and maintainer errors. The log is
`service.log` beside the socket.

One maintainer per logical corpus refreshes on mount and every 300 seconds.
Proxies heartbeat every 30 seconds; mount leases expire after 120 seconds.
Unmount releases the lease; the daemon shuts down after 60 seconds without
mounts or active work. A removed checkout can fail over to another mounted
worktree. Writers are locked per corpus. Unchanged snapshots skip row/vector
materialization, parsing and embeddings. Failed refreshes preserve publication.

The daemon fingerprint includes runtime source, lockfile, interpreter and key
installed dependency versions. Different implementations cannot attach to the
same live daemon. After changing those files:

1. Disconnect this repository's MCPs in every loaded worktree/location.
2. Run `sh .opencode/search/search.sh service stop` for its database.
3. Install the same updated runtime/lock across worktrees and run setup.
4. Reconnect the MCPs and verify their snapshot and service health.

## Agent hooks and other clients

OpenCode V2 starts project `mcp.servers` automatically. MCP lifespan hooks mount
and refresh, renew leases and unmount on exit. The project plugin at
`.opencode/plugins/repo-search.js` adds search-resolution reminders through
V2 `context` and `compaction` hooks using a dependency-free `setup` entry point. Slash commands
provide explicit health/sync actions. `AGENTS.md` and the portable skill are
the durable search-and-edit contract.

Other stdio MCP clients can use the same command array from
`.opencode/search/mcp.fragment.json`, with one server per corpus. Set their
working directory to the target repository root; use absolute paths if the
client cannot set `cwd`. The client configuration shape is client-specific.
The skill under `.claude/skills/` is discoverable by Claude Code and OpenCode;
agents with another skill location can copy it or read it through `AGENTS.md`.

## Troubleshooting

- **Profile absent:** installed policy has not reached the configured upstream
  branch. Commit/publish it through the ordinary workflow, then `catalog`/`sync`.
- **No chunks:** correct include/exclude/extensions, add suitable committed text
  or leave that corpus disabled in MCP configuration. Empty refreshes preserve
  old complete generations and report failure.
- **Invalid note:** correct title/Source/Pagination declarations, UTF-8, stem and
  stable source identifier, or select the general `source` parser for that text.
- **Unknown currency:** inspect fetch/refresh errors and upstream access; explicit
  `sync` retries immediately. A complete old snapshot remains usable as a baseline.
- **Different implementation:** disconnect outdated mounts, stop the daemon,
  synchronize runtime/lockfiles, then reconnect.
- **JSONC config:** the installer intentionally requests `--fragment-only`; merge
  its `mcp.servers` fragment by hand to preserve comments and other configuration.
- **Conflicting file/server:** inspect the local customization before integrating
  an update; the installer refuses differing payloads and unmanaged collisions.

Runtime dependencies and model files are downloaded on first use. The search
environment stays separate from repository application dependencies. For an
offline host, provision the locked environment/model cache beforehand; fetching
upstream still needs access to the configured Git remote.

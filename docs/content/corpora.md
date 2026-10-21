<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# Corpus management

Keep owned source, general reference text and scientific-note evidence separate.
Each named corpus has its own MCP server and logical index; compatible corpora in
one database share a daemon and embedding model.

| Built-in corpus | Starting content | Parser | Default MCP |
| --- | --- | --- | --- |
| `repository` | Code, tests, durable docs and configuration | `source` | `lancedb` |
| `articles` | Literature notes under `reference/literature/`, `docs/literature/`, `literature/` | `reference_note` | `lancedb-articles` |
| `references` | General text under `kb/`, `docs/references/`, `reference/notes/` | `source` | `lancedb-references` |

Only `repository` starts enabled. Arbitrary lowercase corpus names are supported;
each needs a distinct MCP server name.

## Natural-language commands

These commands are on current `main`, **newer than the rc.1 tag**:

```text
/search-corpus-add Scientific paper notes in docs/papers; propose a papers corpus
/search-corpus-update papers Also include literature/notes, keeping existing paths
/search-corpus-update papers --apply --sync Also include literature/extra
```

The agent inspects your policy, Git/source paths and representative samples to
infer a draft—not bibliographic facts. It previews the exact change, selected-file
counts, inspection commit, note errors, overlap and rebuild scope. Confirm before
applying, or explicitly request `--apply`. Empty or ambiguous input asks for
purpose, paths and the target corpus rather than inventing a selection.

### Broadening versus replacing

Updates append include/exclude/extension lists by default. Existing paths and
unrelated corpora/settings stay intact. Explicit replacement/removal uses
`--replace-lists` in the helper. Existing parser/server identities cannot be
changed in place; create a new corpus instead.

For overlap, explicitly approve changing another corpus's exclusions. The helper's
repeatable `--exclude-from OTHER` flag appends the target include patterns to those
corpora's exclusions. It does not guess ownership or change other corpora silently.

### Apply and sync

- Preview/inspection is dependency-free, does not fetch or pin policy, and starts
  no runtime or daemon.
- Apply uses a revision token bound to the current settings, policy and exact
  proposal. Stale/changed proposals need a new preview.
- The validated profile is published in one atomic replace. Owned installation
  hashes are updated; nothing stages, commits, pushes or changes Git visibility.
- `--sync` requests reconciliation. A failed sync leaves the policy applied and
  reports the failure instead of pretending the index is ready.
- Without `--sync`, the running OpenCode watcher can still connect newly enabled
  MCPs and start their normal initial indexing.

!!! warning "Private-policy edits can rebuild every enabled corpus"
    The entire private profile is identified by one hash. Changing it gives all
    its corpora new table identities and changes the default database. An explicit
    database stays at its path, but table identities still change. Old indexes are
    retained. Requested private sync reconciles all enabled corpora after a change.

Shared-policy edits must reach the configured upstream branch before indexing.
The helper returns `publication_required` rather than syncing stale shared policy.
Publish through your usual Git workflow, then run:

```text
/mcps
/search-sync --corpus papers
/search-status --corpus papers
```

## Manual policy

Read the `profile` field in `.opencode/search-package/runtime.json`. The default
is `.opencode/search-package/profiles.json`; migrated integrations keep their
original path. Add an object under `corpora`, for example:

```json
"standards": {
  "enabled": true,
  "server": "lancedb-standards",
  "description": "Engineering standards",
  "parser": "source",
  "source_kind": "reference",
  "include": ["docs/standards/**"],
  "exclude": [],
  "extensions": [".md", ".rst", ".txt"]
}
```

Paths are repository-relative, case-sensitive `fnmatch` patterns. In that syntax,
`*` can match `/`; exclusions matter. Exclude deliberately separate reference paths
from `repository` and other corpora when you want independent coverage.

Native profile edits reload automatically. Portable installations rerun
`install.py REPOSITORY --configure-only --corpora repository,standards` to refresh
their selected MCP definitions. Shared policy must be published before reconnecting.

## Scientific notes and extracted text

Use `reference_note` only for committed Markdown with a real top-level title and
literal `**Source:**` / `**Pagination:**` declarations. Source needs a DOI, stable
URL or arXiv identifier; the filename stem is the `paper_id` used by filters.

Use `source` for ordinary reference text and already-extracted paper text without
those note declarations. Do not add guessed identifiers, page numbers or verification
claims just to satisfy a parser. Mixed collections may need separate corpora.

PDF/OCR/full-text ingestion is not implemented. `tracked_note` and `note_fragment`
describe committed note excerpts, not independent full-text verification;
`extraction_page` remains null. Read the owning note and verify the original source
before citing it. See the [full format](operations.md#literature-note-format).

Enabled corpora with no selected files or malformed scientific notes in the
inspected commit cannot be applied by the helper. Prepare a future corpus disabled
until its suitable source files are published.

## Direct helper

Use the exact package launcher supplied by the command/context hook, followed by:

```text
corpus inspect --root WORKTREE
corpus add NAME --spec PROPOSAL.json --dry-run --root WORKTREE
corpus update NAME --spec PATCH.json --dry-run --root WORKTREE
corpus update NAME --spec PATCH.json --apply --expect-revision REVISION --sync --root WORKTREE
```

`--spec -` reads JSON from stdin. Add takes a complete corpus object; update takes
a partial patch. Do not pass the slash command's natural-language description
directly as shell arguments. The [operations manual](operations.md#native-corpus-management)
contains the complete agent execution workflow and [profile field reference](operations.md#profile-fields).

<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# Contributor guidance

## Scope and layout

This is the standalone `opencode-repo-search` project. Read `README.md` and
`payload/docs/agent-search.md` before changing its installation or search contracts.

- `install.py`: dependency-free repository installer and configuration merge.
- `plugin/` and `package.json`: native ESM entrypoint, lazy cached bootstrap and
  package-owned project initialization.
- `payload/.opencode/search/repo_search/`: Git snapshots, parsing, indexing,
  querying, shared daemon and MCP proxy.
- `payload/.opencode/search/pyproject.toml` and `uv.lock`: isolated Python runtime.
- `payload/.opencode/plugins/repo-search.js`: OpenCode V2 context/compaction hooks.
- `payload/.claude/skills/` and `payload/.opencode/commands/`: installed guidance.
- `tests/test_bundle.py`: portable installer and runtime integration checks.
- `tests/test_package.py` and `tests/test_plugin.mjs`: installed npm artifact,
  runtime bootstrap, real MCP and JavaScript registration/lifecycle checks.

The package entrypoint is under development; release-candidate publication and
installer-to-package migration are the next stages described in `README.md`.

## Contracts

- Index the configured committed upstream branch. Shared policy comes from that
  same snapshot; private policy is an immutable local snapshot identified by hash.
- Installation never stages or commits implicitly. Only an explicit `git-commit`
  action may create a commit; `git-ignore` uses local Git excludes.
- Discover branch, staged, dirty and untracked changes through local Git/source.
  Resolve retrieved paths and anchors against current source before edits.
- Keep repository, article-note and general-reference corpora independent.
  Literature-note excerpts are discovery leads, not verified full-text extraction.
- Publish complete immutable generations through atomic manifest pointers.
  A failed refresh retains the last complete snapshot and reports its currency.
- Share one compatible daemon/model cache per resolved database across connections
  and worktrees; isolate independent projects by default.
- Keep the runtime independent of the target project's Python environment and
  application packages. Preserve the BSD license and copyright notices.
- Check current OpenCode V2 documentation before changing plugin APIs or config.

## Verification

Run functional tests in the shipped locked environment from the repository root:

```sh
sh verify.sh
npm test
```

Run Python quality checks with the repository's Ruff configuration:

```sh
uv tool run --from ruff==0.15.21 ruff check .
uv tool run --from ruff==0.15.21 ruff format --check .
```

For installer-only checks, use `install.py --dry-run` against a Git worktree with
an upstream configured. Exercise changed runtime behavior with the integration
suite. Check relevant local diffs and source anchors before handing work off.

Keep environments, databases, sockets, model downloads and generated caches out
of Git and release archives.

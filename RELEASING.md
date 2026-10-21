<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# Release workflow

## Candidate preparation

1. Update `package.json`, `CHANGELOG.md` and the pinned installation examples in
   `README.md` on a release branch. Keep prereleases explicit, for example
   `0.1.0-rc.1` with the tag `v0.1.0-rc.1`.
2. Run `sh verify.sh`, `npm test`, Ruff lint/format, syntax/license checks and
   `uv lock --project payload/.opencode/search --python 3.12 --check`.
3. Open a release PR and obtain passing Linux/macOS and quality/bundle CI results.
4. Create and push an annotated candidate tag at that exact commit. Tags also
   trigger CI; it checks that the tag matches the npm package version.

## Candidate acceptance

Exercise actual Git-package installation with isolated OpenCode state:

```sh
python3.12 tests/smoke_opencode.py --migration \
  --git-package 'github:VanaMartin/opencode-repo-search#v0.1.0-rc.1'
```

Repeat against a local real-project source clone and a pinned source baseline:

```sh
python3.12 tests/accept_project.py \
  --source /path/to/local/source-clone --commit BASELINE_COMMIT \
  --git-package 'github:VanaMartin/opencode-repo-search#v0.1.0-rc.1' \
  --profile /path/to/customized/profiles.json \
  --query 'representative source concept' --expect-path src/example.py
```

This runner makes a fresh clone, redirects its upstream to an acceptance-owned
local bare repository, and adds two explicitly synthetic committed reference
fixtures. The supplied source clone is read-only. It copies the optional custom
policy, enables the three built-in corpora, includes the two fixture paths and
excludes them from repository search. It verifies source anchors/provenance,
independent corpora, local Git-delta exclusion, tracked/staged/dirty preservation,
one compatible model/daemon across two OpenCode worktrees, automatic upstream
refresh and zero reembedding for unchanged source. Allow several minutes for
initial indexing and the normal 300-second refresh interval.

Both runners print their isolated-state directory and write `report.json` on
success. They stop owned servers/daemons; retained logs and reports are local
diagnostics. Do not include real-project source or query excerpts in release assets.

## GitHub publication

Use assets from the successful **tag** CI run, rather than rebuilding them:

```sh
gh run download RUN_ID --name opencode-repo-search-release-COMMIT --dir release-assets
cd release-assets
shasum -a 256 -c SHA256SUMS
```

The artifact contains versioned source and npm tarballs plus `SHA256SUMS`. Review
the archive file lists for caches, databases, environment directories, sockets,
machine paths and unrelated project content. Create a GitHub prerelease at the
candidate tag with those three files, linking the passing CI and acceptance
results. Candidate tags are immutable; use a new candidate number for fixes.

## Stable and npm publication

After candidate acceptance/review, update to the stable version and installation
examples, repeat checks, tag validation and Git-package acceptance, and publish a
stable GitHub release from the successful tag CI assets.

An authenticated npm publisher can publish the **verified npm tarball**:

```sh
npm whoami
npm publish ./opencode-repo-search-VERSION.tgz --access public --tag next  # candidate
# Stable versions use --tag latest instead.
```

Use `next` for prereleases so candidates do not become the default npm install.
Verify `npm view opencode-repo-search dist-tags --json` and run actual OpenCode
installation using the published npm version. npm authentication and stable
publication are separate from GitHub candidate distribution.

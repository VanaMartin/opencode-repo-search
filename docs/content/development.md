<!--
SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
-->

# Development and documentation

## Repository layout

| Path | Responsibility |
| --- | --- |
| `plugin/`, `index.js`, `package.json` | Native registration, lazy bootstrap and project/corpus management. |
| `install.py` | Dependency-free portable installer and configuration merging. |
| `payload/.opencode/search/repo_search/` | Git snapshots, parsing, indexing, query, daemon and MCP proxy. |
| `payload/.opencode/search/pyproject.toml`, `uv.lock` | Isolated locked search runtime. |
| `payload/docs/agent-search.md` | Canonical shipped operations/agent guidance. |
| `tests/` | Portable/npm-installed integration, lifecycle and live acceptance checks. |
| `docs/content/`, `mkdocs.yml`, `docs/hooks.py` | Documentation pages, site configuration and canonical-reference inclusion. |

Read the repository's `AGENTS.md` before changing installation/search contracts.
Keep databases, sockets, environments, models and generated sites out of Git and
release archives. Preserve the BSD license and source headers.

## Functional and quality checks

Run from the repository root:

```sh
sh verify.sh
npm test
uv tool run --from ruff==0.15.21 ruff check .
uv tool run --from ruff==0.15.21 ruff format --check .
uv lock --project payload/.opencode/search --python 3.12 --check
```

`verify.sh` uses the shipped locked environment and temporary Git repositories,
not the target application's dependencies. Tests cover actual LanceDB/MiniLM,
MCP, installation, provenance, refresh, failure retention and daemon sharing.
The JavaScript suite exercises registrations, natural-language routing, reloads
and lifecycle cleanup. Node.js 22+ and npm are needed for package tests.

Live OpenCode acceptance can also exercise Git-package loading, installer adoption
and running corpus edits:

```sh
python3.12 tests/smoke_opencode.py --migration --corpora
python3.12 tests/smoke_opencode.py \
  --git-package 'github:VanaMartin/opencode-repo-search#REVISION'
```

For fresh-clone real-project acceptance, see the [release workflow](releasing.md).
Retained diagnostics are local; never include private-project source in public assets.

## Build and preview this site

Documentation has its own small locked environment under `docs/`, separate from
the CPU search runtime and any target project:

```sh
uv lock --project docs --python 3.12 --check
uv run --project docs --python 3.12 --frozen mkdocs build --strict
python3.12 scripts/check_docs.py --site-dir site
uv run --project docs --python 3.12 --frozen mkdocs serve
```

The preview is mounted under `/opencode-repo-search/` to match GitHub Pages.
The generated `site/` directory is ignored. Search, responsive navigation and
light/dark mode are supplied by the built-in MkDocs theme; no analytics are enabled.

The operations manual, changelog and release workflow are included directly from
their canonical source files during the build. Do not maintain duplicate copies
under `docs/content/`. Strict builds validate navigation and Markdown anchors;
the HTML checker validates local links/assets/anchors under the Pages base path
and the README's relative links.

## CI badges and Pages

README badges use the actual `main` branch check names for quality, Linux/macOS
integration and verified bundles. They are not four relabeled aggregate results.
The documentation badge tracks the separate Documentation workflow.

- **CI:** quality/lockfile/syntax/license checks, Linux/macOS installed-artifact
  integration and verified source/npm archives with release checksums.
- **Documentation build:** a frozen dependency set, strict build and link checks
  run on pull requests, pushes to `main` and manual dispatch.
- **Pages deploy:** runs only from `main`, after the documentation build passes.
  It uses the `github-pages` environment and minimal Pages/OIDC permissions.
  Pull requests can build/upload artifacts but cannot deploy production Pages.

Repository setup is **Settings → Pages → Build and deployment → GitHub Actions**.
The expected site is <https://vanamartin.github.io/opencode-repo-search/>.
On a fork, enable Pages and adjust `site_url`, repository/edit links and badges to
the new owner/repository. Never add a deployment token to a pull-request workflow.

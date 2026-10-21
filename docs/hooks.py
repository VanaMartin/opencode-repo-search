"""Publish canonical references without maintaining duplicate documentation copies.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

from pathlib import Path

from mkdocs.structure.files import File

ROOT = Path(__file__).resolve().parents[1]
REFERENCES = {
    "operations.md": "payload/docs/agent-search.md",
    "releasing.md": "RELEASING.md",
    "changelog.md": "CHANGELOG.md",
}


def on_files(files, config):
    for destination, source in REFERENCES.items():
        files.append(File.generated(config, destination, content=(ROOT / source).read_text()))
    return files


def on_page_context(context, page, config, **kwargs):
    if source := REFERENCES.get(page.file.src_uri):
        page.edit_url = f"{config.repo_url}/blob/main/{source}"
    return context

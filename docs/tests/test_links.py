"""Regressions for documentation links and GitHub Pages subpath deployment.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))

from check_docs import check_readme, check_site  # noqa: E402


class DocumentationLinks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="repo-search-doc-links-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.site = self.root / "site"
        self.write(
            "index.html",
            '<link rel="canonical" href="https://example.invalid/project/">'
            '<a href="guide/#section">Guide</a><link href="assets/site.css">',
        )
        self.write(
            "guide/index.html", '<h1 id="section">Guide</h1><a href="/project/#overview">Home</a>'
        )
        self.write("assets/site.css", "body { color: black; }")
        self.write("search/search_index.json", '{"docs":[{"title":"Overview"}]}')
        self.append("index.html", '<h1 id="overview">Overview</h1>')

    def write(self, name, content):
        path = self.site / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def append(self, name, content):
        path = self.site / name
        path.write_text(path.read_text() + content)

    def test_valid_subpath_links_and_external_urls(self):
        self.append(
            "index.html",
            '<a href="https://example.net/outside">External</a>'
            '<a href="mailto:test@example.invalid">Email</a>',
        )
        self.assertEqual(check_site(self.site), [])

    def test_missing_page_asset_and_anchor(self):
        self.append(
            "index.html",
            '<a href="missing/">Missing</a><script src="lost.js"></script>'
            '<a href="guide/#wrong">Wrong anchor</a>',
        )
        errors = check_site(self.site)
        self.assertEqual(len(errors), 3)
        self.assertTrue(any("anchor #wrong" in error for error in errors))

    def test_wrong_absolute_base_path(self):
        self.append("index.html", '<a href="/guide/">Not under the project base</a>')
        self.assertIn("outside the Pages base path", check_site(self.site)[0])

    def test_same_site_absolute_urls_are_validated(self):
        self.append("index.html", '<a href="https://example.invalid/project/absent/">Missing</a>')
        self.assertIn("target is missing", check_site(self.site)[0])

    def test_path_escape_is_rejected(self):
        self.append("index.html", '<a href="../private.txt">Outside</a>')
        self.assertIn("outside the generated site", check_site(self.site)[0])

    def test_css_assets_and_search_are_checked(self):
        self.write("assets/site.css", "body { background: url('missing.png'); }")
        self.write("search/search_index.json", '{"docs":[]}')
        errors = check_site(self.site)
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("missing.png" in error for error in errors))

    def test_readme_paths_and_heading_anchors(self):
        (self.root / "README.md").write_text(
            "# Overview\n\n[Home](#overview) [Guide](guide.md#install)\n"
        )
        (self.root / "guide.md").write_text("# Install\n")
        self.assertEqual(check_readme(self.root), [])
        (self.root / "guide.md").write_text("# Renamed\n")
        self.assertIn("heading anchor is missing", check_readme(self.root)[0])
        (self.root / "guide.md").unlink()
        self.assertIn("target is missing", check_readme(self.root)[0])


if __name__ == "__main__":
    unittest.main()

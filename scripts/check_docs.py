"""Check generated local links/assets/anchors and README links without network access.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import argparse
import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.ids = set()
        self.links = []
        self.canonical = None
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if identity := attrs.get("id"):
            self.ids.add(identity)
        if tag == "a" and attrs.get("name"):
            self.ids.add(attrs["name"])
        if tag == "link" and "canonical" in attrs.get("rel", "").split():
            self.canonical = attrs.get("href")
        if tag in {"a", "link"} and "href" in attrs:
            self.links.append(attrs["href"])
        if tag in {"img", "script", "iframe", "source"} and "src" in attrs:
            self.links.append(attrs["src"])


def local_target(site, origin, prefix, source, url):
    parsed = urlsplit(url)
    if parsed.scheme or parsed.netloc:
        if parsed.scheme not in {"http", "https"} or parsed.netloc != origin:
            return None
    path = unquote(parsed.path)
    if path.startswith("/"):
        if not path.startswith(prefix):
            raise ValueError("outside the Pages base path")
        target = site / path.removeprefix(prefix)
    elif path:
        target = source.parent / path
    else:
        target = source
    target = target.resolve()
    if not target.is_relative_to(site):
        raise ValueError("outside the generated site")
    if target.is_dir():
        target /= "index.html"
    if not target.is_file():
        raise ValueError("target is missing")
    return target, unquote(parsed.fragment)


def check_site(directory):
    site = directory.resolve()
    pages = {path: Page(path.read_text()) for path in site.rglob("*.html")}
    index = pages.get(site / "index.html")
    canonical = urlsplit(index.canonical or "") if index else urlsplit("")
    if not canonical.netloc or not canonical.path.endswith("/"):
        return ["index.html must have an absolute canonical URL ending in /"]
    errors = []
    references = {path: page.links for path, page in pages.items()}
    for path in site.rglob("*.css"):
        references[path] = re.findall(r"url\(\s*['\"]?([^)'\"\s]+)", path.read_text())
    for path, links in references.items():
        for url in links:
            try:
                resolved = local_target(site, canonical.netloc, canonical.path, path, url)
                if resolved is None:
                    continue
                target, anchor = resolved
                if anchor and target.suffix == ".html" and anchor not in pages[target].ids:
                    raise ValueError(f"anchor #{anchor} is missing")
            except ValueError as error:
                errors.append(f"{path.relative_to(site)} -> {url}: {error}")
    search = site / "search/search_index.json"
    if not search.is_file() or not json.loads(search.read_text()).get("docs"):
        errors.append("search/search_index.json is missing or empty")
    return errors


def heading_ids(text):
    result = set()
    counts = {}
    # Ignore code blocks when resolving GitHub-style README heading anchors.
    text = re.sub(r"(?ms)^```.*?^```\s*$", "", text)
    for heading in re.findall(r"(?m)^#{1,6}\s+(.+?)\s*#*\s*$", text):
        anchor = re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")
        suffix = counts.get(anchor, 0)
        counts[anchor] = suffix + 1
        result.add(anchor + (f"-{suffix}" if suffix else ""))
    return result


def check_readme(root):
    root = root.resolve()
    readme = root / "README.md"
    text = readme.read_text()
    errors = []
    for url in re.findall(r"!?\[[^\]]*\]\(([^\s)]+)(?:\s+\"[^\"]*\")?\)", text):
        parsed = urlsplit(url)
        if parsed.scheme or parsed.netloc:
            continue
        target = (root / unquote(parsed.path)).resolve() if parsed.path else readme
        if not target.is_relative_to(root) or not target.exists():
            errors.append(f"README.md -> {url}: target is missing or outside the repository")
        elif parsed.fragment and target.suffix == ".md":
            if unquote(parsed.fragment) not in heading_ids(target.read_text()):
                errors.append(f"README.md -> {url}: heading anchor is missing")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-dir", type=Path, default=ROOT / "site")
    args = parser.parse_args()
    errors = check_site(args.site_dir) + check_readme(ROOT)
    if errors:
        parser.exit(1, "\n".join(errors) + "\n")
    print("Site links, assets, anchors, search index and README links are valid.")


if __name__ == "__main__":
    main()

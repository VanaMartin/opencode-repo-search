"""Inspect committed paths for advisory corpus setup without fetching or indexing.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import fnmatch
from collections import Counter
from pathlib import Path

from repo_search.articles import paper_metadata
from repo_search.git_source import read_blobs
from repo_search.installation import git


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def selected(path, policy):
    return (
        matches(path, policy["include"])
        and not matches(path, policy["exclude"])
        and (
            Path(path).suffix in policy["extensions"]
            or matches(path, policy.get("extensionless_files", []))
        )
    )


def inspect_repository(root, profile, settings):
    remote, branch = settings.get("remote", "origin"), settings.get("branch", "main")
    reference = f"refs/remotes/{remote}/{branch}"
    resolved = git(root, "rev-parse", "--verify", reference + "^{commit}", check=False)
    basis = "cached_upstream"
    if resolved.returncode:
        reference, basis = "HEAD", "local_commit"
        resolved = git(root, "rev-parse", "--verify", "HEAD^{commit}", check=False)
    if resolved.returncode:
        return {"basis": "no_commit", "corpora": {}, "advisory": True}
    commit = resolved.stdout.strip()
    blobs = {}
    for entry in git(root, "ls-tree", "-r", "-z", commit).stdout.split("\0"):
        if not entry:
            continue
        metadata, path = entry.split("\t", 1)
        mode, kind, oid = metadata.split()
        if kind == "blob" and mode in {"100644", "100755"}:
            blobs[path] = oid
    corpora = {}
    for name, policy in profile["corpora"].items():
        paths = [path for path in blobs if selected(path, policy)]
        corpora[name] = {
            "enabled": policy["enabled"],
            "selected_files": len(paths),
            "sample_paths": paths[:5],
            "suggested_includes": [],
            "suggested_excludes": [],
        }
        if policy["parser"] == "reference_note":
            invalid = []
            raw = read_blobs(root, list(dict.fromkeys(blobs[path] for path in paths)))
            for path in paths:
                try:
                    paper_metadata(path, raw[blobs[path]].decode("utf-8"))
                except (UnicodeError, ValueError) as error:
                    invalid.append({"path": path, "error": str(error)})
            corpora[name].update(invalid_notes=len(invalid), note_errors=invalid[:5])
    policy = profile["corpora"].get("repository")
    if policy:
        groups = Counter()
        ignored = {
            "node_modules",
            ".venv",
            "__pycache__",
            "target",
            "dist",
            "build",
            "vendor",
            "third_party",
            ".opencode",
            ".claude",
            ".worktrees",
        }
        for path in blobs:
            if (
                Path(path).suffix not in policy["extensions"]
                or ignored.intersection(Path(path).parts)
                or matches(path, policy["exclude"])
                or selected(path, policy)
            ):
                continue
            group = path.split("/", 1)[0] + "/**" if "/" in path else path
            groups[group] += 1
        corpora["repository"]["suggested_includes"] = [
            {"pattern": pattern, "additional_files": count}
            for pattern, count in sorted(groups.items())[:20]
        ]
    reference_parts = {
        "kb",
        "knowledge",
        "knowledge-base",
        "reference",
        "references",
        "literature",
        "papers",
        "articles",
    }
    candidates = [
        path
        for path in blobs
        if Path(path).suffix in {".md", ".mdx", ".rst", ".txt"}
        and reference_parts.intersection(Path(path).parts[:-1])
        and not {".opencode", ".claude", "node_modules", "vendor"}.intersection(Path(path).parts)
    ]
    raw = read_blobs(root, list(dict.fromkeys(blobs[path] for path in candidates)))
    for path in candidates:
        try:
            paper_metadata(path, raw[blobs[path]].decode("utf-8"))
            note = Path(path).suffix == ".md"
        except (UnicodeError, ValueError):
            note = False
        repository = profile["corpora"].get("repository")
        if repository and selected(path, repository):
            exclusions = corpora["repository"]["suggested_excludes"]
            if len(exclusions) < 20:
                exclusions.append(
                    {
                        "pattern": path,
                        "selected_files": 1,
                        "reason": "Candidate for an independent reference corpus",
                    }
                )
        for name, policy in profile["corpora"].items():
            is_reference = name == "references" or policy.get("source_kind") == "reference"
            if (
                not selected(path, policy)
                and not matches(path, policy["exclude"])
                and Path(path).suffix in policy["extensions"]
                and (policy["parser"] == "reference_note" if note else is_reference)
            ):
                suggestions = corpora[name]["suggested_includes"]
                if len(suggestions) < 20:
                    suggestions.append({"pattern": path, "additional_files": 1})
    overlaps = Counter()
    for path in blobs:
        owners = [
            name
            for name, policy in profile["corpora"].items()
            if policy["enabled"] and selected(path, policy)
        ]
        if len(owners) > 1:
            overlaps[", ".join(owners)] += 1
    return {
        "basis": basis,
        "ref": reference,
        "commit": commit,
        "advisory": True,
        "corpora": corpora,
        "overlapping_files": dict(overlaps),
        "next": "Review include suggestions and corpus counts before enabling corpora; "
        "this cached committed-tree inspection is not an index or freshness check",
    }

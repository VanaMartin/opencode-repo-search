"""Preview or publish a release candidate as the floating Git tag `latest`.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LATEST = "refs/tags/latest"


def git(repo, *arguments):
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments], capture_output=True, text=True, timeout=120
    )
    if result.returncode:
        detail = "\n".join(part for part in (result.stderr.strip(), result.stdout.strip()) if part)
        raise ValueError(detail or "Git command failed")
    return result.stdout.strip()


def remote_tags(repo, url, candidate):
    refs = (f"refs/tags/{candidate}", LATEST)
    result = {}
    for line in git(
        repo, "ls-remote", "--tags", "--", url, *refs, *(ref + "^{}" for ref in refs)
    ).splitlines():
        oid, ref = line.split("\t")
        if not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", oid):
            raise ValueError("Remote returned an invalid Git object ID")
        result[ref] = oid
    return result


def promote(repo, candidate, remote="origin", *, push=False):
    number = r"(?:0|[1-9][0-9]*)"
    if not re.fullmatch(rf"v{number}\.{number}\.{number}-rc\.{number}", candidate):
        raise ValueError("Specify a versioned candidate tag, for example v0.1.0-rc.2")
    if remote not in git(repo, "remote").splitlines():
        raise ValueError(f"Not a configured Git remote: {remote}")
    # Inspect and push to the same destination, even when origin has a separate
    # push URL. Refuse ambiguous multi-destination pushes.
    urls = git(repo, "remote", "get-url", "--push", "--all", remote).splitlines()
    if len(urls) != 1:
        raise ValueError("Promotion requires exactly one push URL")
    url = urls[0]
    refs = remote_tags(repo, url, candidate)
    source = f"refs/tags/{candidate}"
    if source not in refs:
        raise ValueError(f"Candidate tag does not exist on {remote}: {candidate}")

    # Download only the advertised candidate object. Do not update local tags,
    # branches or FETCH_HEAD, and do not inherit tag pruning from user config.
    git(
        repo,
        "-c",
        "fetch.prune=false",
        "-c",
        "fetch.pruneTags=false",
        "fetch",
        "--no-tags",
        "--no-write-fetch-head",
        "--no-recurse-submodules",
        "--",
        url,
        refs[source],
    )
    commit = git(repo, "rev-parse", refs[source] + "^{commit}")
    if commit != refs.get(source + "^{}", refs[source]):
        raise ValueError("Candidate does not resolve to the advertised commit")
    manifest = json.loads(git(repo, "show", commit + ":package.json"))
    if not isinstance(manifest, dict) or manifest.get("version") != candidate.removeprefix("v"):
        raise ValueError("Candidate tag does not match package.json version")

    previous = refs.get(LATEST)
    previous_commit = refs.get(LATEST + "^{}", previous)
    result = {
        "candidate": candidate,
        "commit": commit,
        "remote": remote,
        "previous_latest": previous_commit,
        "state": "unchanged" if previous_commit == commit else "preview",
    }
    if not push or previous_commit == commit:
        return result

    # A lightweight alias needs no local tag rewrite or signing identity. The
    # explicit lease rejects concurrent moves/creation of latest. Only this ref
    # may be pushed, including when push.followTags is enabled in user config.
    git(
        repo,
        "push",
        "--porcelain",
        "--no-follow-tags",
        f"--force-with-lease={LATEST}:{previous or ''}",
        "--",
        url,
        f"{commit}:{LATEST}",
    )
    published = remote_tags(repo, url, candidate)
    if published.get(LATEST + "^{}", published.get(LATEST)) != commit:
        raise ValueError(
            "Push completed but latest no longer matches; inspect the remote before retrying"
        )
    result["state"] = "updated"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("candidate", help="Already validated/published tag, e.g. v0.1.0-rc.2")
    parser.add_argument("--remote", default="origin", help="Configured remote (default: origin)")
    parser.add_argument("--repo", type=Path, default=ROOT, help="Release repository checkout")
    parser.add_argument(
        "--push", action="store_true", help="Move/create remote latest; default is preview"
    )
    args = parser.parse_args()
    try:
        print(json.dumps(promote(args.repo, args.candidate, args.remote, push=args.push), indent=2))
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"Promotion failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Profile validation and repository-scoped database defaults.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import os
import re
from pathlib import Path

from repo_search.chunks import sha256


def validate_profile(profile: dict) -> None:
    if profile.get("format") != "repo-search-profiles-v1":
        raise ValueError("Expected repo-search-profiles-v1")
    embedding = profile["embedding"]
    if embedding["registry"] != "sentence-transformers" or embedding["device"] != "cpu":
        raise ValueError("This runtime supports the sentence-transformers CPU registry")
    if (
        not 0
        <= embedding["overlap_tokens"]
        < embedding["chunk_target_tokens"]
        <= embedding["chunk_max_tokens"]
        < embedding["total_input_max_tokens"]
    ):
        raise ValueError("Invalid tokenizer budgets")
    if not isinstance(embedding["dimensions"], int) or embedding["dimensions"] < 1:
        raise ValueError("Embedding dimensions must be positive")
    corpora = profile.get("corpora")
    if not isinstance(corpora, dict) or not corpora:
        raise ValueError("Define at least one corpus")
    servers = set()
    for name, policy in corpora.items():
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError("Corpus names must be lowercase identifiers")
        if policy.get("parser") not in {"source", "reference_note"}:
            raise ValueError(f"Unknown parser for {name}")
        server = policy.get("server")
        if not isinstance(server, str) or not re.fullmatch(r"[a-z][a-z0-9_-]*", server):
            raise ValueError(f"Invalid MCP server name for {name}")
        if server in servers:
            raise ValueError("Each corpus needs a distinct MCP server name")
        servers.add(server)
        if not isinstance(policy.get("enabled"), bool):
            raise ValueError(f"Set enabled to true or false for {name}")
        for key in ("include", "exclude", "extensions"):
            values = policy.get(key)
            if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
                raise ValueError(f"{name}.{key} must be a list of strings")
        if not policy["include"] or not policy["extensions"]:
            raise ValueError(f"{name} needs include patterns and extensions")
        if policy["parser"] == "reference_note" and policy["extensions"] != [".md"]:
            raise ValueError("reference_note corpora accept Markdown notes only")


def database_path(source, explicit: Path | None = None) -> Path:
    """Share worktrees of one upstream/profile; isolate different repositories by default."""
    override = explicit or os.environ.get("REPO_SEARCH_DB")
    if override:
        return Path(override).expanduser().resolve()
    identity_key = source.repo_id + "\n" + source.profile_path
    if source.policy_hash:
        identity_key += "\nlocal:" + source.policy_hash
    identity = sha256(identity_key)[:20]
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local/share")))
    return (base / "repo-search" / identity / "lancedb").expanduser().resolve()

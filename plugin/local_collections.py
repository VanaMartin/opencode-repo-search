"""Capture native defaults for independent local collections without provisioning.

SPDX-License-Identifier: BSD-3-Clause
License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE
"""

import json
from pathlib import Path

from configuration import resolve
from repo_search.git_source import MainSource
from repo_search.local_registry import LocalRegistry, digest, encoded, make_profile
from repo_search.settings import database_path


def creation_inputs(root, policy, database=None):
    """Read current defaults; never pin normal policy, fetch or create its database."""
    configuration = resolve(root)
    root = Path(configuration["root"])
    config, profile = configuration["settings"], configuration["profile"]
    if config is None:
        profile = json.loads(
            (
                Path(__file__).resolve().parents[1] / "payload/.opencode/search/profiles.json"
            ).read_bytes()
        )
    selected_database = database
    if config is not None and database is None:
        policy_hash = None
        if config.get("policy_source", "upstream") == "local":
            # Match normal private-policy identity without pin_profile's write.
            raw = (json.dumps(profile, sort_keys=True, ensure_ascii=False) + "\n").encode()
            policy_hash = digest(raw)
        source = MainSource.discover(
            root,
            remote=config.get("remote", "origin"),
            branch=config.get("branch", "main"),
            profile=config["profile"],
            policy_hash=policy_hash,
        )
        selected_database = database_path(source, Path(config["db"]) if config.get("db") else None)
    return {
        "profile": make_profile(profile["embedding"], policy),
        "database": selected_database,
        "context_revision": digest(
            encoded(
                {
                    "configuration": configuration,
                    "database": str(selected_database) if selected_database else None,
                }
            )
        ),
    }


def preview(root, name, policy, *, ref="HEAD", database=None):
    registry = LocalRegistry.discover(root)
    return registry.preview(name, ref=ref, **creation_inputs(root, policy, database))


def create(root, name, policy, *, expect_revision, ref="HEAD", database=None):
    registry = LocalRegistry.discover(root)
    return registry.create(
        name,
        expect_revision=expect_revision,
        ref=ref,
        context_check=lambda: creation_inputs(root, policy, database)["context_revision"],
        **creation_inputs(root, policy, database),
    )

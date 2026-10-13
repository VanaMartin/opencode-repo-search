#!/bin/sh
# SPDX-License-Identifier: BSD-3-Clause
# License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE

set -eu
BUNDLE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
HERE="$BUNDLE/payload/.opencode/search"
cd "$HERE"
exec uv run --project "$HERE" --python 3.12 --frozen --group dev \
  python -m pytest -c "$HERE/pyproject.toml" "$BUNDLE/tests" "$@"

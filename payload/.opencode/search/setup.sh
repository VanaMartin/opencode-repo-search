#!/bin/sh
# SPDX-License-Identifier: BSD-3-Clause
# License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE

set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
uv sync --project "$HERE" --python 3.12 --frozen
exec sh "$HERE/search.sh" catalog "$@"

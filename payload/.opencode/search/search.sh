#!/bin/sh
# SPDX-License-Identifier: BSD-3-Clause
# License: https://github.com/VanaMartin/opencode-repo-search/blob/main/LICENSE

set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$HERE/../.."
exec uv run --project "$HERE" --python 3.12 --frozen python "$HERE/run.py" "$@"

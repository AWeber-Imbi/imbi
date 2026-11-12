#!/usr/bin/env bash
# Regenerate ui/src/types/api-generated.ts from the imbi-api code.
#
#   scripts/regen-api-types.sh          write the file
#   scripts/regen-api-types.sh --check  fail when the checked-in file is stale
#
# No running API or database is needed (see scripts/dump_openapi.py).
# The apache-iggy wheel does not load on macOS, so on macOS the dump
# runs in a Linux container, with its own virtualenv in a docker volume.
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
spec="$root/ui/openapi.json"

if [ "$(uname -s)" = "Darwin" ]; then
    docker run --rm \
        -v "$root:/src" -w /src \
        -v imbi-regen-api-types-venv:/venv \
        -v imbi-regen-api-types-uv-cache:/root/.cache/uv \
        -e UV_PROJECT_ENVIRONMENT=/venv \
        -e UV_LINK_MODE=copy \
        -e RUSTFLAGS=--cap-lints=warn \
        ghcr.io/astral-sh/uv:python3.14-bookworm \
        sh -c 'uv sync --frozen --all-groups --all-extras --quiet && uv run --frozen --no-sync python scripts/dump_openapi.py' \
        > "$spec"
else
    uv --directory "$root" run --frozen python scripts/dump_openapi.py > "$spec"
fi

npm --prefix "$root/ui" run --silent codegen

if [ "${1:-}" = "--check" ]; then
    git -C "$root" diff --exit-code -- ui/src/types/api-generated.ts || {
        echo "ui/src/types/api-generated.ts is stale. Run scripts/regen-api-types.sh and commit the result." >&2
        exit 1
    }
fi

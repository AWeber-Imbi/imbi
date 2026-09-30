#!/usr/bin/env bash
#
# Install the pinned pglifecycle build and print the path of the binary.
#
# pglifecycle has no release with the features that schemata/ needs, so
# the moon schema tasks and CI build one commit of its main branch
# (execution plan D27). Change PGLIFECYCLE_REV here and in
# schemata/README.md together. CI caches the install directory with a
# key that includes the hash of this file.
#
# Usage:
#   schemata/scripts/install-pglifecycle.sh   # prints the binary path
#
# Environment:
#   PGLIFECYCLE          use this binary and do not install
#   PGLIFECYCLE_ROOT     the install directory (default: a cache
#                        directory that includes the commit)

set -euo pipefail

PGLIFECYCLE_REPO='https://github.com/gmr/pglifecycle'
PGLIFECYCLE_REV='1e5b893054271e30891682c00197606b0bdb0291'

if test -n "${PGLIFECYCLE:-}"; then
    echo "$PGLIFECYCLE"
    exit 0
fi

cache="${XDG_CACHE_HOME:-$HOME/.cache}"
root="${PGLIFECYCLE_ROOT:-$cache/imbi/pglifecycle/$PGLIFECYCLE_REV}"
binary="$root/bin/pglifecycle"

if ! test -x "$binary"; then
    echo "Building pglifecycle $PGLIFECYCLE_REV into $root" >&2
    cargo install --locked --quiet \
        --git "$PGLIFECYCLE_REPO" --rev "$PGLIFECYCLE_REV" \
        --root "$root" pglifecycle >&2
fi

echo "$binary"

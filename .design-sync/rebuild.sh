#!/usr/bin/env bash
# Library build + converter build + validate, each log under .cache/.
set -uo pipefail
cd "$(dirname "$0")/.."
mkdir -p .design-sync/.cache
.design-sync/lib-build/build.sh > .design-sync/.cache/lib-build.log 2>&1 || { echo "lib build failed"; tail -20 .design-sync/.cache/lib-build.log; exit 1; }
node .ds-sync/package-build.mjs --config .design-sync/config.json --node-modules ui/node_modules --out ./ds-bundle "$@" > .design-sync/.cache/build.log 2>&1 || { echo "build failed"; tail -30 .design-sync/.cache/build.log; exit 1; }
node .ds-sync/package-validate.mjs ./ds-bundle > .design-sync/.cache/validate.log 2>&1
status=$?
echo "validate exit=$status"
exit "$status"

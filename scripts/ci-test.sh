#!/usr/bin/env bash
# Run the Python test suite for root:coverage.
#
# With IMBI_TEST_BASE unset (local runs, pushes to main), run every
# member's tests and apply the whole-tree coverage floor from the root
# pyproject.
#
# With IMBI_TEST_BASE set (pull requests), run only the tests of the
# members that the change affects, plus the members that depend on them
# (moon's project graph). Then apply each member's own coverage floor
# from its pyproject to its own source. A change to a file that every
# member shares (root config, lockfile, test fixtures, CI) runs the full
# suite.
set -euo pipefail

mkdir -p build

full() {
    echo "ci-test: $1, running the full suite"
    exec uv run --frozen --env-file .env.test pytest -n auto --cov \
        --cov-report=term-missing --cov-report=xml:build/coverage.xml
}

base="${IMBI_TEST_BASE:-}"
if [ -z "$base" ]; then
    full "no IMBI_TEST_BASE"
fi
if ! changed=$(git diff --name-only "$base"...HEAD); then
    full "cannot diff against $base"
fi

# Files that every member's tests read.
if grep -qE '^(pyproject\.toml|uv\.lock|conftest\.py|compose\.ci\.yaml|\.prototools|\.moon/|\.github/workflows/test\.yml|scripts/ci-test\.sh|scripts/iggy_config_server\.py)' <<<"$changed"; then
    full "shared test input changed"
fi

# The root project owns every file, so drop it. Keep only Python
# members (the projects that have a pyproject.toml).
sources=$(jq -Rn '{files: [inputs | select(length > 0)]}' <<<"$changed" |
    moon query projects --affected --downstream deep |
    jq -r '.projects[] | select(.id != "root") | .source')
# The workflows tests import imbi.api, but moon does not let one
# application depend on another, so that edge is here.
if grep -qx 'apps/api' <<<"$sources"; then
    sources+=$'\napps/workflows'
fi
members=()
tests=()
while read -r src; do
    if [ -n "$src" ] && [ -f "$src/pyproject.toml" ] && [ -d "$src/tests" ]; then
        members+=("$src")
        tests+=("$src/tests")
    fi
done < <(sort -u <<<"$sources")

if [ ${#members[@]} -eq 0 ]; then
    echo "ci-test: no Python member affected, skipping tests"
    exit 0
fi

echo "ci-test: affected members: ${members[*]}"
# The whole-tree floor does not apply to a partial run; the member
# floors below replace it.
uv run --frozen --env-file .env.test pytest -n auto --cov \
    --cov-fail-under=0 --cov-report=xml:build/coverage.xml "${tests[@]}"

status=0
for src in "${members[@]}"; do
    echo "ci-test: coverage for $src"
    uv run --frozen coverage report --rcfile="$src/pyproject.toml" \
        --include="$src/src/*" || status=1
done
exit "$status"

#!/usr/bin/env bash
#
# Bump every workspace member's version in lockstep.
#
# Versions here are lockstep by design: the meta-package, every app,
# libraries/common, every plugin, and the UI package all carry the same
# version, and cross-member dependencies are exact pins on it. That is 15
# `version =` lines plus 27 `imbi-*==<version>` pins plus ui/package.json --
# too many to edit by hand without drift.
#
# Usage:
#   scripts/bump-version.sh <new-version>   # rewrite everything to <new-version>
#   scripts/bump-version.sh --check         # assert lockstep, print the version
#
# Edits files only. Committing and tagging are the caller's job -- see
# .claude/skills/release/SKILL.md.
#
# helm/imbi/Chart.yaml is deliberately NOT touched: a Helm chart version is
# independent of the application version it ships.

set -euo pipefail

cd "$(dirname "$0")/.."

ROOT_PYPROJECT="pyproject.toml"
UI_PACKAGE_JSON="ui/package.json"

# Every pyproject that carries a lockstep version and/or a member pin.
# Kept as a whitespace-separated list rather than an array: this has to run
# under the bash 3.2 that ships with macOS, which has no `mapfile`.
PYPROJECTS="$ROOT_PYPROJECT $(
  ls -1 apps/*/pyproject.toml libraries/*/pyproject.toml plugins/*/pyproject.toml
)"

die() {
  printf 'bump-version: %s\n' "$*" >&2
  exit 1
}

current_version() {
  perl -ne 'if (/^version = "([^"]+)"/) { print "$1\n"; last }' "$ROOT_PYPROJECT"
}

# Print "<file>: <kind> <version>" for every lockstep version we track, so
# --check can compare them and a bump can verify it left nothing behind.
# Exactly one unindented `version = "..."` exists per pyproject; the indented
# matches are the cross-member pins.
collect_versions() {
  # shellcheck disable=SC2086  # $PYPROJECTS is a deliberate argument list
  perl -ne '
    print "$ARGV: version $1\n" if /^version = "([^"]+)"/;
    print "$ARGV: pin $1\n" if /^\s+"imbi-[a-z-]+(?:\[[^\]]*\])?==([^"]+)"/;
  ' $PYPROJECTS
  printf '%s: version %s\n' "$UI_PACKAGE_JSON" \
    "$(jq -r .version "$UI_PACKAGE_JSON")"
}

check() {
  local versions distinct majority covered expected
  versions=$(collect_versions)

  # A gate that passes because it found nothing is worse than no gate. If a
  # version line is ever reformatted, the patterns above stop matching it and
  # the comparison below would silently narrow to whatever still parses.
  #
  # Count `version` entries, not distinct files: a file whose own version line
  # stopped parsing still shows up via its pin, so file coverage alone would
  # not notice. Every pyproject carries exactly one, plus package.json.
  covered=$(printf '%s\n' "$versions" | awk '$2 == "version"' | wc -l | tr -d ' ')
  # shellcheck disable=SC2086  # deliberate word split onto one file per line
  expected=$(($(printf '%s\n' $PYPROJECTS | wc -l) + 1)) # +1 for package.json
  if [ "$covered" -ne "$expected" ]; then
    die "read a project version from $covered of $expected files;" \
      "has a 'version =' line been reformatted?"
  fi
  if ! printf '%s\n' "$versions" | grep -q ' pin '; then
    die "found no imbi-*== cross-member pins; has the pin format changed?"
  fi

  distinct=$(printf '%s\n' "$versions" | awk '{print $3}' | sort -u)
  if [ "$(printf '%s\n' "$distinct" | wc -l | tr -d ' ')" -ne 1 ]; then
    # Report the odd ones out rather than all 43 lines: the majority version
    # is almost always the intended one, so the minority is the drift.
    majority=$(printf '%s\n' "$versions" | awk '{print $3}' | sort | uniq -c |
      sort -rn | head -1 | awk '{print $2}')
    printf 'bump-version: versions are NOT in lockstep (most are %s):\n' \
      "$majority" >&2
    printf '%s\n' "$versions" | awk -v m="$majority" '$3 != m' | sort -u >&2
    exit 1
  fi
  printf '%s\n' "$distinct"
}

bump() {
  local new="$1" old file remaining
  old=$(current_version)
  [ -n "$old" ] || die "could not read the version from $ROOT_PYPROJECT"

  # Refuse to bump a tree that is already inconsistent -- otherwise the
  # rewrite silently leaves the odd file behind on its own version.
  check >/dev/null

  [ "$new" != "$old" ] || die "already at $new"

  # perl rather than sed -i, whose in-place syntax differs between the BSD sed
  # on macOS and GNU sed on Linux.
  for file in $PYPROJECTS; do
    OLD="$old" NEW="$new" perl -i -pe '
      # The project'"'"'s own version. Anchored to a bare version = "..." at the
      # start of a line, which no dependency pin can match.
      s/^version = "\Q$ENV{OLD}\E"$/version = "$ENV{NEW}"/;
      # Cross-member pins: imbi-common==, imbi-plugin-github==, and friends,
      # with or without an extras bracket.
      s/("imbi-[a-z-]+(?:\[[^\]]*\])?)==\Q$ENV{OLD}\E"/$1==$ENV{NEW}"/g;
    ' "$file"
  done

  # Updates package.json and package-lock.json together, which a bare edit of
  # package.json does not.
  (cd ui && npm version "$new" --no-git-tag-version >/dev/null)

  uv lock

  remaining=$(collect_versions | awk -v v="$old" '$3 == v')
  if [ -n "$remaining" ]; then
    printf 'bump-version: still on %s after the rewrite:\n' "$old" >&2
    printf '%s\n' "$remaining" >&2
    exit 1
  fi

  printf 'Bumped %s -> %s\n\n' "$old" "$new"
  git status --short
}

case "${1-}" in
  --check) check ;;
  -h | --help | '') sed -n '3,19p' "$0" | sed 's/^#\{1,2\} \{0,1\}//' ;;
  -*) die "unknown option: $1" ;;
  *)
    case "$1" in
      [0-9]*.[0-9]*.[0-9]*) ;;
      *) die "not a semantic version: $1" ;;
    esac
    bump "$1"
    ;;
esac

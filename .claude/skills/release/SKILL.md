---
name: release
description: Cut an Imbi release end to end — bump the lockstep version, write release notes matching the last few releases, create the signed annotated tag, push it, and confirm the GitHub release. Use when asked to cut/tag/ship a release, release a specific version ("release 2.31.0"), or publish release notes for the monorepo.
---

# Cutting an Imbi release

One pass, in order, no steps skipped. Every step is here because it has gone
wrong at least once.

Use `GH_HOST=github.com gh` for every `gh` call — `origin` is
`git@github.com:AWeber-Imbi/imbi.git` on GitHub Cloud, while the default `gh`
host here is AWeber's Enterprise instance.

## The three rules that keep breaking

1. **The tag must be annotated.** `2.26.1` was cut lightweight.
2. **The tag message must be exactly the release notes**, with no version
   subject line. `gh --notes-from-tag` uses the *whole* annotation (it reads
   `%(contents)` and strips only `%(contents:signature)`), so a leading
   `2.31.0` line becomes a stray line at the top of the release body. `2.30.0`
   was annotated with nothing but `2.30.0`.
3. **Always pass `--cleanup=verbatim`, and end the notes with exactly one
   newline.** `git tag`'s default cleanup is `strip`, which deletes every line
   beginning with `#` as "commentary" — it silently ate every `## Fixes`
   heading from `2.29.2`, `2.29.3`, and `2.29.4`. Tags here are SSH-signed, and
   without a final newline verbatim mode glues `-----BEGIN SSH SIGNATURE-----`
   onto the last line of the notes.

`release.yml` now fails within a minute on all three, but the point is not to
get there.

## Step 0 — preflight

```sh
git rev-parse --abbrev-ref HEAD          # must be main
git status --porcelain                   # must be empty
git pull --ff-only
GH_HOST=github.com gh auth status
scripts/bump-version.sh --check          # lockstep intact before we touch it
```

## Step 1 — pick the version and bump it

Release tags, oldest to newest. Sort on the v-stripped version but keep the
real tag name: `v` sorts above digits, so both `sort -V` and git's own
`--sort=version:refname` leave the legacy `v2.17.0` ranked highest forever,
and the compare link needs a name that actually exists.

```sh
releases() {
  git tag --list --merged HEAD | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' \
    | while read -r t; do printf '%s\t%s\n' "${t#v}" "$t"; done \
    | sort -V | cut -f2
}
prev=$(releases | tail -1)
```

If the user named a version, use it. Otherwise read `"$prev"..HEAD` and choose:
minor for any new capability, patch for fixes and internal changes only. Say
which you picked and why before doing it.

Then set `TAG` to what you picked. Everything from here on refers to it, so
nothing above this line can — an unset `TAG` makes the checks below inspect
the empty tag name and `bump-version.sh` print its help instead of bumping:

```sh
TAG=2.31.0                               # the version you just chose
```

The target version must not already exist. All three of these must come back
empty or fail:

```sh
git tag --list "$TAG"
git ls-remote --tags origin "refs/tags/$TAG"
GH_HOST=github.com gh release view "$TAG" --repo AWeber-Imbi/imbi
```

```sh
scripts/bump-version.sh "$TAG"
```

That rewrites all 15 `pyproject.toml` files (versions *and* the 27
`imbi-*==` cross-member pins), `ui/package.json` + `ui/package-lock.json`, and
`uv.lock` — 18 files. Never hand-edit them. Review the diff, then commit and
push to `main` following the `git-repository:git-commit` skill:

```sh
git commit -am "Bump version to $TAG"      # matches the existing convention
git push origin main
```

## Step 2 — gather the material

Ask the API which PR each commit belongs to. **Do not scrape `(#N)` off commit
subjects** — this repo uses squash merges *and* real merge commits, so only
some commits carry the suffix. In the 2.29.4..2.30.0 range exactly one of five
subjects had one; scraping would have found #290 and silently missed #288 and
#289, which is most of that release.

```sh
prs=$(git rev-list "$prev"..HEAD | while read -r sha; do
  GH_HOST=github.com gh api "repos/AWeber-Imbi/imbi/commits/$sha/pulls" \
    -q '.[].number'
done | sort -un)
```

Read every PR — the notes are written from PR bodies, not commit subjects:

```sh
for n in $prs; do
  GH_HOST=github.com gh pr view "$n" --repo AWeber-Imbi/imbi \
    --json number,title,body,url
done
```

Follow any issue a PR body closes and read that too. The house style cites the
originating issue inline, and the issue is usually where the user-visible
symptom is stated in the reporter's own words.

Cross-check against `git log --format='%s' "$prev"..HEAD` for anything that
landed without a PR (the version bump aside) — it needs a bullet too.

## Step 3 — write the notes in the *current* house style

**Read the last three releases first and mirror them.** Do not use a template
from this file — the style genuinely moves (2.26.0/2.27.0 used `###`; 2.29.0
used `## Added`/`## Changed`/`## Removed`/`## Fixed`; 2.28.0 and 2.30.0 use
`## Features`/`## Fixes`/`## Changes`). Whatever the last few releases did is
what this release does.

```sh
for t in $(releases | tail -3); do
  echo "===== $t ====="
  GH_HOST=github.com gh release view "$t" --repo AWeber-Imbi/imbi \
    --json body -q .body
done
```

Use the `releases` helper from step 1, not `git tag --sort=-version:refname`
— that ranks the legacy `v2.17.0` first and would hand you a 2023-era
auto-generated "## What's Changed" release as a style exemplar.

Match their heading vocabulary, ordering, and bullet shape. These invariants
hold across the whole corpus and are not up for reinterpretation:

- **One bullet per user-visible change, not per PR.** A single PR routinely
  yields several bullets — `#289` produced three Features and one Fix in
  2.30.0 — and two PRs fixing one thing yield one bullet.
- **Bullet shape:** `- **<lede>** ([#N](<pr url>)) — <prose>`. The lede is the
  *symptom* for a fix ("The promotion popover offered promotes the API was
  guaranteed to refuse"), the *capability* for a feature. Never a commit
  subject, never a file name.
- **The prose carries the mechanism, the consequence, and the fix**, in the
  operator's terms. This is the distinguishing feature of these notes: say how
  many rows change, what config needs no change, what is still broken and
  until when, what was verified against what. Read 2.29.4 and 2.30.0 for the
  bar.
- **Close with the compare link**, as its own last paragraph:
  `**Full changelog**: https://github.com/AWeber-Imbi/imbi/compare/<prev>...<TAG>`
- No emoji, no `🤖`, no `Co-Authored-By`, no "generated with" trailer.
- **Do not start the file with the version number** (rule 2 above).

Write it to a scratch file outside the repo — the session scratchpad, never a
tracked path — ending with exactly one newline. Then **show the notes to the
user and get approval before tagging.** The notes are the one part of this a
human should sign off on, and an annotated tag is awkward to correct after it
is pushed.

## Step 4 — create the annotated tag

```sh
git tag -a --cleanup=verbatim -F "$NOTES" "$TAG"
```

Then prove it round-tripped, which is what would have caught 2.26.1 and
2.29.2/3/4:

```sh
[ "$(git cat-file -t "$TAG")" = tag ] || echo "NOT ANNOTATED"
diff <(git for-each-ref "refs/tags/$TAG" --format='%(contents)' \
        | sed '/-----BEGIN SSH SIGNATURE-----/,$d') "$NOTES"
```

`diff` must print nothing. If it prints anything at all, `git tag -d "$TAG"`,
fix the cause, and start this step over — **do not push a tag that failed the
round-trip.**

If the tag fails to sign, **stop and tell the user.** Do not retry with
`--no-sign`, do not fall back to `-m`.

## Step 5 — push the tag

```sh
git push origin "$TAG"
```

## Step 6 — wait for the release workflow

The run does not exist the instant the push returns, so find it before
watching it:

```sh
for _ in $(seq 30); do
  run=$(GH_HOST=github.com gh run list --repo AWeber-Imbi/imbi \
          --workflow release.yml --branch "$TAG" --limit 1 \
          --json databaseId -q '.[0].databaseId')
  [ -n "$run" ] && break
  sleep 5
done
GH_HOST=github.com gh run watch "$run" --repo AWeber-Imbi/imbi --exit-status
```

`--branch "$TAG"` works because a tag push reports the tag as `headBranch`.

Judge success on the **run's** conclusion, not on any job's status — a job can
still read `in_progress` after its run has already succeeded.

If the run fails, read the failing job's log
(`gh run view "$run" --log-failed`) and report it. Re-running the workflow is
safe: the image push, the PyPI publish (`skip-existing`), and the release
creation are all idempotent.

## Step 7 — confirm the GitHub release

`release.yml`'s `github-release` job creates it from the tag. Verify:

```sh
GH_HOST=github.com gh release view "$TAG" --repo AWeber-Imbi/imbi \
  --json tagName,name,body,url
# `isLatest` is not a gh release view field; ask the API instead:
GH_HOST=github.com gh api repos/AWeber-Imbi/imbi/releases/latest -q .tag_name
```

`name` must be exactly `$TAG` and `body` must match the approved notes. If the
release is **missing** — the workflow died before reaching that job — create it
with the same command the workflow uses.

`--latest` is not optional here. Left to decide for itself, `gh` marks the
newest release *by date* as latest, so a patch cut on an older line would
demote a newer release. `release.yml` computes it from the same
highest-semver comparison that decides the image's `:latest` tag, and the
fallback has to reach the same answer — the workflow exits early when the
release already exists, so a rerun will not correct a wrong choice:

```sh
highest=$(git tag | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' | sed 's/^v//' \
  | sort -V | tail -n 1)
[ "$highest" = "${TAG#v}" ] && is_latest=true || is_latest=false

GH_HOST=github.com gh release create "$TAG" --repo AWeber-Imbi/imbi \
  --verify-tag --notes-from-tag --title "$TAG" --latest="$is_latest"
```

This needs the tags present locally (`git fetch --tags`), for the same reason
the workflow's `github-release` job checks out at `fetch-depth: 0`.

Do not hand-write the body with `--notes`; the annotation is the source of
truth.

Finish by reporting the release URL, the published image tags
(`ghcr.io/aweber-imbi/imbi:$TAG`, `aweber/imbi:$TAG`, plus `:latest` if this is
the highest semver), and whether the release is marked latest.

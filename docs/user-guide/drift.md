# Drift

Drift tells you that a project has work that is not released or not
promoted. Imbi uses the word for three different things. Each one has its
own badge and its own data.

| Kind | Question it answers | Where you see it |
|---|---|---|
| Environment drift | Does an environment run different code from the next environment in its pipeline? | `Δ T → S` badges on the projects list, the **Ready to ship** icon on the **Deployments** tab |
| Commit-to-release drift (C → R) | Does a releasable project have commits after its latest release tag that need a release? | `Δ C → R` badge on the projects list, the **Ready to ship** icon on the **Releases** tab |
| Release drift | Did CI report configuration drift on the commit of one release? | The **Drift** badge on a release in the release history, and a `drift` blocker |

The **Drifted** count on the projects list counts only the first two kinds.
It never reads release drift.

## Drift verdicts from CI

Imbi does not calculate drift from your files. Your CI pipeline decides,
for each commit, if the commit changes something that needs a release. CI
writes the answer as a git note on the commit, in the
`refs/notes/imbi-drift` namespace:

```json
{"drift_detected": false}
```

A note can also have `drift_paths`, a list of the paths that caused a
`true` verdict. Imbi ignores a note that is not valid JSON or that has no
boolean `drift_detected`. Imbi stores each verdict in the ClickHouse
`commit_drift` table, one row for each commit.

Each commit has one of three states:

| State | Meaning |
|---|---|
| `false` | CI checked the commit. Nothing in it needs a release |
| `true` | CI checked the commit. It needs a release |
| No verdict | CI wrote no note, or Imbi has not read the note yet |

### The rule: only proven clean is clean

Imbi shows drift unless CI answered `false` for **every** commit in the
range. One `true` verdict shows drift. One commit with no verdict also
shows drift. Imbi does this so that a missing note can never hide work.

Thus a project whose CI writes no drift notes shows drift for every
difference. To hide drift for commits that do not matter (for example,
documentation or CI configuration), make your CI write a `false` note for
those commits.

When Imbi cannot read the verdict store, it also shows drift.

### How verdicts get into Imbi

| Path | When it runs |
|---|---|
| The gateway action **Update Release Drift from Notes Push** | On each push to the notes ref, when an administrator configured the webhook rule. See [Gateway](../gateway/index.md) |
| **Sync Commits & Tags** | When you run it. It reads the whole notes ref again and records the verdicts that Imbi does not have yet |
| The **Close Out Stuck Deployments** maintenance operation (`deployment-sweep`) | When an administrator runs it from **Admin > Global Admin > Maintenance**. It reads all the notes of a project one time. Then, on each run, it asks for at most 10 releases with no verdict, and asks again for one release at most every 24 hours |

If a webhook delivery was lost, a commit stays with no verdict and shows
drift. To repair it, open the **Doctor** tab (the stethoscope icon) and
click **Sync Commits & Tags**. The button shows when you have
`project:commits:write`.
The sync icon on the **Releases** and **Deployments** tabs runs the same
commit sync.

A removed note does not remove the verdict. Imbi keeps the last verdict
that it recorded.

## Environment drift

Environments are in one list, ordered by their sort order. An environment
with the **terminal** flag ends a pipeline. The next environment starts a
new pipeline. Imbi compares each pair of adjacent environments in one
pipeline. It never compares across the end of a pipeline.

For each pair, Imbi compares the commit that each environment runs:

1. If the two commits are the same, there is no drift. A different tag on
   the same commit is not drift.
2. If the commits are different, Imbi finds the commits between them. The
   pair shows drift unless every one of those commits has the verdict
   `false`.
3. If Imbi cannot find both commits, or cannot put them in order, the pair
   shows drift.

The earlier environment in the pipeline runs the newer code. For example,
with **Testing**, **Staging**, and **Production**, the pair "Testing →
Staging" shows drift when Testing runs commits that are not in Staging
yet.

### The badge

The projects list shows one badge for each pair with drift, for example
`Δ T → S`. The letters are the initials of the environment names. The
badge has the color of the target environment, or amber when the target
has no color.

Click the badge to open the **Deployments** tab of the project, with the
target environment selected. From there you can promote. See
[Releases and deployments](releases-and-deployments.md).

The badge shows only for a project with a deployable project type.

## Commit-to-release drift (C → R)

This kind applies to a project with a releasable project type. The range is
the commits after the commit of the latest release tag. Imbi finds the
latest tag with the same rule as the **Releases** tab.

The badge `Δ C → R` (amber) shows when:

- there is at least one commit after the latest tag, and
- the range is not proven clean (see [the rule](#the-rule-only-proven-clean-is-clean)).

Click the badge to open the **Releases** or **Deployments** tab of the
project, where you can cut a release.

A project with no release tag has no C → R range and shows no C → R badge.

## Release drift

A release has its own drift value. It is the CI verdict for the one commit
that the release tag points at. It is not a value for the range of commits
in the release.

| Value | Meaning |
|---|---|
| `true` | CI reported drift on this commit |
| `false` | CI reported no drift |
| Not set | Imbi has not seen a note for this commit |

When the value changes to `true`, Imbi adds a blocker of type `drift` to the
release, with the description "CI reported configuration drift on commit
\<sha\>". When a later verdict is not `true`, Imbi resolves that blocker
with the note "drift note cleared". A blocked release cannot be promoted.
See [Blockers](releases-and-deployments.md#blockers).

In the release history, a release with the value `true` shows the amber
badge **Drift**. Hover over it to see "CI reported configuration drift on
this release's commit".

## Drift on the projects list

| Control | What it does |
|---|---|
| **Drifted** chip | Shows the number of projects with at least one `Δ` badge. Click it to show only those projects |
| **Drift** column filter | Select one or more pairs, for example `S → P` or `C → R (commit → release)`. Each option shows its count |

The URL keeps the filters (`has_drift=1` and `drifts=`), so you can share
a filtered list.

## Drift on the project page

### Ready to ship

The **Deployments** tab (or the **Releases** tab) shows a rocket icon,
**Ready to ship**, when:

- **Deployments**: two adjacent environments run different commits.
- **Releases**: the project has commits after its latest tag.

This icon does not use the CI verdicts. It can show when the projects list
shows no badge, because the list hides a range that is proven clean.

### Commit markers

Commit lists on the **Deployments** and **Releases** tabs show one marker
for each commit:

| Marker | Tooltip | Meaning |
|---|---|---|
| Amber package icon | **Drift Detected** | The verdict is `true`, or there is no verdict |
| Gray circle with a line | **No Drift Detected** | The verdict is `false` |

The card that counts commits ready to release counts all commits after the
tag. It does not use the verdicts.

## Troubleshooting

| Problem | Cause and fix |
|---|---|
| Every project shows drift | Your CI writes no drift notes. Each commit has no verdict, so Imbi shows it. Add a CI step that writes a note for each commit |
| A badge stays after CI wrote `false` notes | Imbi did not receive the notes push. Click **Sync Commits & Tags** on the **Doctor** tab |
| A badge stays for one old commit | A commit made before your CI wrote notes has no verdict. Write a note for that commit, or release and promote past it |
| The rocket shows, but the list shows no badge | The rocket ignores verdicts. The list hides a range where every commit is `false` |

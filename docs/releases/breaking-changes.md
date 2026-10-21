# Breaking Changes

Imbi versions releases with [semantic versioning](https://semver.org):
a breaking change ships in a new **major** version (`2.4.1` → `3.0.0`),
so consumers who pin `2.x` are not broken by it. Below `1.0.0` the
**minor** version carries breaking changes instead (`0.4.2` → `0.5.0`).

A breaking change is one that breaks a consumer who upgrades without
changing anything on their side, for example:

- removing or renaming an endpoint, field, function, command, flag,
  event, or configuration key
- changing a default, a response or payload shape, or a behavior
  consumers rely on, in a way their existing usage no longer works with
- dropping support for a runtime, platform, or API version

Who the consumers are depends on the project: a library's public API, a
service's HTTP, event, or queue contract with other services, a CLI's
flags and output.

## Mark breaking commits

The author knows best when a change is breaking, so say so in the
commit, using the [Conventional Commits](https://www.conventionalcommits.org)
markers. Either one is enough:

- a `!` before the colon of the subject:

    ```text
    feat(api)!: remove the v1 export endpoint
    ```

- a `BREAKING CHANGE:` footer in the body, saying what consumers must
  change:

    ```text
    Remove the v1 export endpoint

    BREAKING CHANGE: clients must call /v2/exports instead.
    ```

For a squash-merged pull request, put the marker in the squash commit:
the PR title for `!`, or the PR description for the footer. The footer
only reaches the commit when the repository's default squash commit
message includes the pull request description; otherwise, paste it into
the commit message when merging.

## What Imbi does with them

When you promote or cut a release, the AI-drafted release notes list the
breaking changes in the range, each linked to its commit, and suggest a
major version (a minor one below `1.0.0`) when there are any. The list
includes every commit marked as above, plus any the model judges
breaking from its message. A commit the model judged breaking is marked
as such, not as one its author declared, so you can weigh it.

If you change the tag to a version that does not announce the breaking
changes, the form asks you to confirm; for a commit its author marked,
the API refuses the release until you do. A confirmed release is
recorded with who confirmed it and when, whether the changes were marked
by their authors or judged by the model, and shows a **Breaking
overridden** badge in the release history, next to the **CI overridden**
badge for releases shipped over a failing CI run.

Only a person can confirm: a service account's promote or release that
needs the confirmation is refused.

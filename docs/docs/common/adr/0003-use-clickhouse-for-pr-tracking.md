# 3. Use ClickHouse for PR tracking

Date: 2026-05-14

## Status

Accepted

## Context

For the requested PR tracking feature we need a way to store and query PR data efficiently.

We will get this data from the GitHub API and from the Imbi GitHub app webhooks coming in through the gateway.

## Decision

We will use ClickHouse as the primary database for storing and querying PR data. Instead of creating functions to maintain the data in the database, we will use a materialized view that populates the table as a Replacing Merge tree, keyed on Project ID and PR number. PR status will be stored as a regular column (updated via replacement) rather than part of the sorting key.

Pull requests, merge requests, and other SCM terminology differences are normalized to _pull requests_ regardless of the source. Pull requests abbreviations follow the GitHub practice of `#{id}`.

## Consequences

Data consistency and availability will be maintained automatically through the Replacing Merge tree, but will require an initial sync. This initial sync will be performed by a separate process that periodically fetches PR data from the GitHub API.

We will be locking in internally to pull request as terminology even if the data comes in from other sources that use other terminology, like GitLab's "Merge Request."

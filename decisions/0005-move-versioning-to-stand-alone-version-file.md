# 5. Move versioning to stand-alone VERSION file

Date: 2021-01-21

## Status

Accepted

## Context

Version for distribution was based on a variable in `imbi/__init__.py`.

## Decision

Manage versioning in the `VERSION` file to make versioning cleaner and more explicit,
as versions can be released for any combination of API updates, Documentation,
and UI updates.

## Consequences

No negative consequences that I can think of at this time.

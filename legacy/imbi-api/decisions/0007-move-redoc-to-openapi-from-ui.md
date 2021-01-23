# 7. Move Redoc to openapi from ui

Date: 2021-01-23

## Status

Accepted

## Context

The Redoc project was setup and installed as part of the ui, even though it's
not currently used there. The static standalone js file was copied to `imbi/static`.

## Decision

Moving the redoc devDependency to the `openapi` directory will
remove it as a dependency for the UI, and address version conflicts.

## Consequences

If we decide to include ReDoc as a tab for a project, we will have to include
it again later.

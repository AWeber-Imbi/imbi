# 12. Project SSM Schema

Date: 2024-06-25

## Status

Accepted

## Context

We need useful URL and API schemas to represent project SSM configuration.
While the GET endpoint returns a full list of params, we'd like to PATCH
parameters for a specific SSM path using JSON-patch in a straightforward way.

One more complicated way to do this is to use the same exact GET endpoint for
PATCH. If so, then we need to include the index in the `path`. The backend
would need to fetch _all_ SSM params from AWS again, sort them, and verify
the specific param with `ETag` and `If-Matches`.

We would also like to update SSM parameter names, in addition to their values
and types. AWS doesn't afford this kind of update, and requires deleting the
existing parameters and then creating new ones.

## Decision

The GET endpoint will return a list of params, which are objects with environment
keys, and value is a sub-object with `value`, `type`, and `self`. `self`
is a new key that will hold URL that represents a param with a specific name
`/projects/{id}/configuration/ssm/{name}`. The name will be URL-encoded. That
URL is where we can perform PATCH requests to update specific parameters' values
and types.

If users update an SSM parameter name, regardless of whether they also update
the values and types, the frontend will perform two requests: first a DELETE
of the old params, then a POST of the new ones.

## Consequences

This will vastly simplify the PATCH endpoint compared to other implementations,
while still using JSON patch in an appropriate way. There will be no way to
directly PATCH a parameter name, but this is in line with AWS anyway. From the
UI it appears as if users updated the name. This will also unify the parameter
schema, keeping it the same in both the items returned from GET and the paths
used for JSON patch. This does not include a GET endpoint at the same URL as the
PATCH (`/projects/{id}/configuration/ssm/{name}`), because it's not yet needed.
However, it is not complicated to add one if needed.

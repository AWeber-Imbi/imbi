# 3. Manage OpenAPI spec in standalone directory

Date: 2021-01-21

## Status

Accepted

## Context

Previously the OpenAPI spec was managed as a series of files out of the `imbi/schema`
directory. Files were independently service by the API's static file handler as
needed, both inside the API for input validation and externally for documentation
rendering.

With the move to using [tornado_openapi3](https://pypi.org/project/tornado-openapi3/),
startup time was slow with the `openapi_core` library needing to assemble the
document from the many fragments that make up the spec for the API.

## Decision

The OpenAPI specification was moved to a top-level directory, `openapi` that
is setup as a NodeJS project. The [swagger-cli](https://www.npmjs.com/package/swagger-cli)
tool was introduced to build a static, single file version of the OpenAPI spec,
which is then placed in the `imbi/templates` directory.

## Consequences

Any changes to the OpenAPI spec require a build step that did not previously exist.
Fortunately this build step has a side effect of doing strict validation of the
OpenAPI document as part of the build process.

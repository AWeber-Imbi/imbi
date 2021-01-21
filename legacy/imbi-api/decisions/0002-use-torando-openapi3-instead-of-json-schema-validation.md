# 2. Use torando_openapi3 instead of JSON Schema validation

Date: 2021-01-21

## Status

Accepted

## Context

Previously, the API would use parts of the OpenAPI spec to validate request
payloads using a JSON Schema validator. With the creation of 
[tornado_openapi3](https://pypi.org/project/tornado-openapi3/), we can simplify
the overall API architecture, validating all requests in the 
`Tornado.web.RequestHandler.prepare()` method. Such validation provides a holistic
approach to request validation, validating the headers, query args, request body,
etc.

## Decision

`tornado_openapi3` has been swapped out for the previous JSON schema behavior
validation approach.

## Consequences

While the validation is more holistic, errors in the API spec will prevent otherwise
successful requests from succeeding. This approach requires a high level of accuracy
in the OpenAPI spec, which given the scope of the API, can be difficult to achieve.

In addition, a non-trivial amount of work was done to refactor the codebase 
to switch to this approach.

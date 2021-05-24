# 9. Use ElasticSearch for Project Search

Date: 2021-05-24

## Status

Accepted

## Context

We would like to add search capability within Imbi to locate projects. Searching
should allow for basic title based search, but also more complex search based upon
specific fields.

## Decision

The project should use ElasticSearch for searching since the syntax is well 
known amd widely adopted.

While we could use the existing tsearch functionality in Postgres, taking this
route will allow for easier, more performant searches across materialized documents.

## Consequences

1. There will be an additional storage backend in the project where we could have just used tsearch.
2. We will need to implement a search results page.
3. We will need to create the ability to build the search index (or rebuild the search index) via a CLI tool.

# Imbi API Client

The `imbi.common.api` subpackage provides an async HTTP client for
talking to the Imbi API and a `pydantic_settings.BaseSettings` class
for configuring it from environment variables.

It is used by services that integrate with Imbi (e.g. `imbi-gateway`)
to record releases, push deployment events, patch project metadata,
and look up users by external identity.

## Overview

`imbi.common.api.client.Imbi` is a thin subclass of
`httpx.AsyncClient` that:

- Sets the `Authorization` and `User-Agent` headers on every request.
- Adds task-oriented helpers for the bookkeeping endpoints
  (`patch_project`, `find_user_by_identity`, `create_release`,
  `record_deployment`).
- Logs non-2xx responses at warning level while still returning the
  raw response so callers can decide how to react.

`imbi.common.api.settings.Settings` loads configuration from
environment variables prefixed with `IMBI_CLIENT_`. The expected
variables are:

| Field          | Environment variable        | Default                 |
| -------------- | --------------------------- | ----------------------- |
| `api_base_url` | `IMBI_CLIENT_API_BASE_URL`  | `http://imbi-api:8000`  |
| `api_token`    | `IMBI_CLIENT_API_TOKEN`     | required                |
| `user_agent`   | `IMBI_CLIENT_USER_AGENT`    | `None` (use the default `imbi-common/{version}`) |

## Basic Usage

```python
from imbi.common.api import Imbi, Settings

settings = Settings()

async with Imbi(
    base_url=str(settings.api_base_url),
    token=settings.api_token.get_secret_value(),
    user_agent=settings.user_agent,
) as client:
    response = await client.create_release(
        'my-org',
        'my-project',
        {'version': '1.2.3', 'title': 'v1.2.3'},
    )
    response.raise_for_status()
```

The constructor parameters mirror what most services want to override
explicitly — base URL, bearer token, optional user-agent, optional
timeout. `Settings` is provided for the common case of pulling those
values from the environment, but callers are free to build an `Imbi`
client from any other source.

## Status-Code Conventions

Two endpoints have idempotency conventions baked into the helpers:

- `create_release` treats `409 Conflict` as success — the release
  already exists — and does **not** log a warning. Other non-2xx
  responses are logged.
- `record_deployment` treats `404 Not Found` as a non-fatal
  "release missing" condition and does **not** log a warning. Other
  non-2xx responses are logged.

In both cases the raw `httpx.Response` is returned so the caller can
distinguish these states from a fully successful 2xx.

## API Reference

### Client

::: imbi.common.api.client.Imbi

### Settings

::: imbi.common.api.settings.Settings

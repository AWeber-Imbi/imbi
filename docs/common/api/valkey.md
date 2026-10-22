# Valkey Client

The Valkey module provides async access to a Valkey (Redis-compatible)
server through the official `valkey-py` async client and integrates with
the FastAPI lifespan dependency-injection pattern.

## Overview

`valkey_lifespan` is an async context manager that constructs a
`valkey.asyncio.Valkey` client from `settings.Valkey().url` and ensures
the client is closed on shutdown. The `Client` type alias wraps the
underlying client with `fastapi.Depends` so it can be injected into
route handlers.

## Basic Usage

```python
from imbi.common import valkey

async with valkey.valkey_lifespan() as client:
    await client.set('greeting', 'hello')
    value = await client.get('greeting')
```

## FastAPI Dependency Injection

```python
import fastapi

from imbi.common import lifespan, valkey

app = fastapi.FastAPI(
    lifespan=lifespan.Lifespan(valkey.valkey_lifespan),
)


@app.get('/greeting')
async def get_greeting(*, client: valkey.Client) -> dict[str, str | None]:
    value = await client.get('greeting')
    return {'value': value.decode() if value else None}
```

## Configuration

`valkey_lifespan` reads the Valkey URL from the `VALKEY_URL` environment
variable, a `.env` file, or the `url` key of the `[valkey]` section of a
`config.toml`, in that order. The default is `valkey://localhost:6379/0`. The setting
accepts only the `valkey://` scheme.

## API Reference

::: imbi.common.valkey.valkey_lifespan

::: imbi.common.valkey.Client

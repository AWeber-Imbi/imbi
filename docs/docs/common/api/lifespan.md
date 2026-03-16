# Lifespan

The lifespan module provides composable FastAPI lifespan management with
type-safe dependency injection.

## Overview

FastAPI accepts only one `lifespan` callable, but applications often need
to manage multiple independent resources—database pools, cache clients,
HTTP sessions—each with its own setup and teardown logic. The `Lifespan`
class composes any number of async context managers (hooks) into a single
lifespan, storing each hook's yielded resource so that dependency
injection functions can retrieve it with full type preservation.

## Basic Usage

```python
import contextlib
import typing
import fastapi
from collections import abc
from imbi_common import lifespan

type PoolType = ...  # your connection pool type


@contextlib.asynccontextmanager
async def db_hook() -> abc.AsyncIterator[PoolType]:
    pool = PoolType(...)
    await pool.open()
    try:
        yield pool
    finally:
        await pool.close()


async def _inject_pool(
    context: lifespan.InjectLifespan,
) -> PoolType:
    return context.get_state(db_hook)


DbPool = typing.Annotated[PoolType, fastapi.Depends(_inject_pool)]

app = fastapi.FastAPI(lifespan=lifespan.Lifespan(db_hook))


@app.get('/items')
async def list_items(*, pool: DbPool) -> list[dict]:
    ...
```

See the [Lifespan and Dependency Injection guide](../guides/lifespan-di.md)
for a full walkthrough of the pattern.

## API Reference

### Type Aliases

::: imbi_common.lifespan.LifespanHook

::: imbi_common.lifespan.TypedLifespanHook

::: imbi_common.lifespan.InjectLifespan

### Classes

::: imbi_common.lifespan.Lifespan

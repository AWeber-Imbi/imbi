# Lifespan and Dependency Injection

This guide explains how to use the `Lifespan` class to manage multiple
application resources and expose them to FastAPI route handlers through
dependency injection.

## Overview

FastAPI's `lifespan` parameter wires up application-level resources—things
that should be initialised once at startup and torn down cleanly at
shutdown. The challenge is that real services need more than one: a
database pool, a cache connection, an HTTP client. `Lifespan` solves this
by composing any number of *hooks* (async context managers) into a single
lifespan, then surfacing each resource through FastAPI's `Depends()`
system with the original type intact.

The five-step pattern is:

1. Define lifespan hooks
2. Combine hooks into a `Lifespan` instance
3. Write dependency injection functions
4. Create `Annotated` type aliases
5. Declare the type aliases as route handler parameters

## Step 1: Define Lifespan Hooks

A hook is an async context manager decorated with
`@contextlib.asynccontextmanager`. It sets up a resource, `yield`s it,
and tears it down on exit.

```python
import contextlib
from collections import abc

import httpx

type HttpClientType = httpx.AsyncClient


@contextlib.asynccontextmanager
async def http_client_hook() -> abc.AsyncIterator[HttpClientType]:
    async with httpx.AsyncClient() as client:
        yield client
```

**Rules:**

- Annotate the return type as `abc.AsyncIterator[YourType]` — the type
  checker uses this to infer the resource type at call sites.
- Yield exactly one value.
- Handle cleanup in the `finally` block or via a nested context manager.

## Step 2: Combine Hooks

Pass hooks to `Lifespan` and use the instance as the FastAPI `lifespan`
parameter:

```python
import fastapi
from imbi_common import lifespan

app = fastapi.FastAPI(
    lifespan=lifespan.Lifespan(http_client_hook)
)
```

If you have multiple resources, list all their hooks:

```python
app = fastapi.FastAPI(
    lifespan=lifespan.Lifespan(
        neo4j_hook,
        redis_hook,
        http_client_hook,
    )
)
```

Hooks are entered in the order listed and cleaned up in reverse
(LIFO) order. If the same hook appears more than once it runs only once,
which means feature modules can each declare their own hook dependencies
without worrying about duplication.

## Step 3: Write Dependency Injection Functions

A DI function accepts `InjectLifespan` (a type alias for the `Lifespan`
instance injected by FastAPI) and returns the resource:

```python
import typing
from imbi_common import lifespan


def _inject_http_client(
    context: lifespan.InjectLifespan,
) -> HttpClientType:
    return context.get_state(http_client_hook)
```

`get_state()` is generic: it accepts a hook typed as
`TypedLifespanHook[T]` and returns `T`. Because `http_client_hook` is
inferred as `TypedLifespanHook[HttpClientType]`, the return type is
`HttpClientType` — no cast required.

For resources that require per-request setup (like acquiring a connection
from a pool), use an async generator instead:

```python
import psycopg_pool

type CursorType = psycopg.AsyncCursor


async def _inject_cursor(
    context: lifespan.InjectLifespan,
) -> abc.AsyncIterator[CursorType]:
    pool = context.get_state(postgres_hook)
    async with pool.connection() as conn:
        async with conn.cursor() as cursor:
            yield cursor
```

## Step 4: Create Type Aliases

Wrap each DI function in an `Annotated` alias so route handlers get both
the type and the injection wired up in one declaration:

```python
HttpClient = typing.Annotated[
    HttpClientType, fastapi.Depends(_inject_http_client)
]

PostgresCursor = typing.Annotated[
    CursorType, fastapi.Depends(_inject_cursor)
]
```

Type checkers treat `HttpClient` as `HttpClientType` everywhere it
appears, so IDE autocomplete and static analysis work as expected.

## Step 5: Use in Route Handlers

Declare the aliases as keyword-only parameters:

```python
@app.get('/health')
async def health_check(
    *,
    client: HttpClient,
) -> dict[str, str]:
    response = await client.get('https://example.com/ping')
    return {'status': 'ok', 'upstream': str(response.status_code)}
```

FastAPI resolves the dependency chain automatically: `HttpClient` →
`_inject_http_client` → `InjectLifespan` → `_get_lifespan`.

## Testing

### Testing a hook in isolation

Use `IsolatedAsyncioTestCase` and enter the hook directly:

```python
import unittest


class HttpClientHookTests(unittest.IsolatedAsyncioTestCase):
    async def test_yields_async_client(self) -> None:
        async with http_client_hook() as client:
            self.assertIsInstance(client, httpx.AsyncClient)
```

### Testing the combined lifespan

```python
class LifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_state_accessible_after_startup(self) -> None:
        func = lifespan.Lifespan(http_client_hook)
        async with func(fastapi.FastAPI()) as result:
            data = result['lifespan_data']
            client = data.get_state(http_client_hook)
            self.assertIsInstance(client, httpx.AsyncClient)
```

### Testing route handlers

Use `TestClient` (which runs the lifespan synchronously):

```python
class HandlerTests(unittest.TestCase):
    def test_health_check(self) -> None:
        with fastapi.testclient.TestClient(app) as client:
            response = client.get('/health')
            self.assertEqual(200, response.status_code)
```

To substitute a lightweight mock for an expensive resource, build a
separate app fixture:

```python
@contextlib.asynccontextmanager
async def mock_http_hook() -> abc.AsyncIterator[httpx.AsyncClient]:
    transport = httpx.MockTransport(handler=my_mock_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        yield client


test_app = fastapi.FastAPI(
    lifespan=lifespan.Lifespan(mock_http_hook)
)
```

## Error Conditions

| Symptom | Cause | Fix |
|---------|-------|-----|
| HTTP 500 `Unmet lifespan dependency hook …` | `get_state()` called with a hook not passed to `Lifespan()` | Add the hook to the `Lifespan` constructor |
| HTTP 500 `Lifespan not available` | No `lifespan=` parameter on the `FastAPI()` constructor, or request state is inaccessible | Ensure `fastapi.FastAPI(lifespan=Lifespan(...))` |
| Type checker: cannot assign `async def … -> AsyncIterator[T]` to `TypedLifespanHook` | Missing or incorrect return type annotation on the hook | Add `-> abc.AsyncIterator[YourType]` to the hook signature |

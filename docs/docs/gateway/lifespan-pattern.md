# Lifespan Management Pattern

## Table of Contents

- [Introduction](#introduction)
- [The Problem](#the-problem)
- [The Solution](#the-solution)
- [Tutorial](#tutorial)
    - [Step 1: Define Lifespan Hooks](#step-1-define-lifespan-hooks)
    - [Step 2: Combine Hooks](#step-2-combine-hooks)
    - [Step 3: Create Dependency Injection Functions](#step-3-create-dependency-injection-functions)
    - [Step 4: Define Type Aliases](#step-4-define-type-aliases)
    - [Step 5: Use in Route Handlers](#step-5-use-in-route-handlers)
    - [Testing Your Lifespan Hooks](#testing-your-lifespan-hooks)
- [API Reference](#api-reference)
- [Advanced Topics](#advanced-topics)
- [Design Rationale](#design-rationale)
- [Troubleshooting](#troubleshooting)

## Introduction

The Lifespan pattern in Imbi Gateway provides a type-safe way to compose
multiple async context managers into a single FastAPI lifespan while
preserving type information through dependency injection. This document
explains the pattern, provides a complete tutorial, and serves as a
reference for implementation and troubleshooting.

**Key Benefits:**

- **Composability:** Combine multiple independent resources into one
  lifespan
- **Type Safety:** Preserve type information through the dependency chain
- **Separation of Concerns:** Each resource manages its own lifecycle
- **Testability:** Resources can be tested independently
- **Hook Deduplication:** Same hook can be passed multiple times without
  duplicate execution

## The Problem

FastAPI's `lifespan` parameter accepts only one callable, but real-world
applications need to manage multiple independent resources with separate
lifecycles. Consider a service that needs both a PostgreSQL connection
pool and a Redis client:

```python
# This DOES NOT work - FastAPI only accepts one lifespan
app = fastapi.FastAPI(
    lifespan=postgres_lifespan,  # Only one allowed!
    lifespan=redis_lifespan,  # This is a syntax error
)
```

You could manually compose them in a single function:

```python
@contextlib.asynccontextmanager
async def combined_lifespan(
        app: fastapi.FastAPI
) -> abc.AsyncIterator[dict[str, object]]:
    async with postgres_lifespan() as postgres:
        async with redis_lifespan() as redis:
            yield {'postgres': postgres, 'redis': redis}


app = fastapi.FastAPI(lifespan=combined_lifespan)
```

**Problems with manual composition:**

1. **Loss of type information:** The yielded dictionary has type
   `dict[str, object]`, losing specific types like `PoolType` and
   `RedisClient`
2. **String-based keys:** Accessing resources requires string keys prone
   to typos: `request.state.postgres` (no autocomplete or type checking)
3. **Tight coupling:** Adding a new resource requires modifying the
   combined function
4. **Error-prone:** No compile-time checks that required resources are
   available

## The Solution

The `Lifespan` class provides a composable, type-safe solution:

```
┌─────────────────────────────────────────────────────────────────┐
│ FastAPI Application                                             │
│                                                                 │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ Lifespan(postgres_lifespan, redis_lifespan)            │     │
│  │                                                        │     │
│  │  Manages:                                              │     │
│  │  - Deduplication (same hook only runs once)            │     │
│  │  - LIFO cleanup order (AsyncExitStack)                 │     │
│  │  - Stores hook → resource mapping                      │     │
│  └────────────────────────────────────────────────────────┘     │
│                           │                                     │
│                           ▼                                     │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ Route Handler                                          │     │
│  │                                                        │     │
│  │  async def handler(                                    │     │
│  │      *, cursor: PostgresCursor, redis: RedisClient     │     │
│  │  ) -> None: ...                                        │     │
│  │                                                        │     │
│  │  FastAPI resolves dependencies via Depends():          │     │
│  │  - PostgresCursor → _get_postgres_cursor()             │     │
│  │  - RedisClient → _get_redis_client()                   │     │
│  └────────────────────────────────────────────────────────┘     │
│                           │                                     │
│                           ▼                                     │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ Dependency Injection Functions                         │     │
│  │                                                        │     │
│  │  def _get_postgres_cursor(                             │     │
│  │      context: InjectLifespan                           │     │
│  │  ) -> AsyncIterator[CursorType]:                       │     │
│  │      pool = context.get_state(postgres_lifespan)       │     │
│  │      # Type of pool is PoolType (preserved!)           │     │
│  │      ...                                               │     │
│  │                                                        │     │
│  │  get_state() is generic and preserves types:           │     │
│  │  - Input: TypedLifespanHook[T]                         │     │
│  │  - Output: T                                           │     │
│  └────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

**How it works:**

1. **Lifespan hooks** are async context managers that yield resources
2. **Lifespan class** combines hooks and stores hook → resource mappings
3. **Dependency injection functions** retrieve resources using
   `get_state(hook)` with full type preservation
4. **Type aliases** (`Annotated[T, Depends(...)]`) enable route handlers
   to declare dependencies
5. **FastAPI** automatically resolves dependencies when handling requests

## Tutorial

This tutorial demonstrates the complete pattern using PostgreSQL and
Redis as examples. These are the actual resource types you'll encounter
in Imbi Gateway.

### Step 1: Define Lifespan Hooks

A lifespan hook is an async context manager that sets up a resource,
yields it, and cleans it up on exit.

**PostgreSQL lifespan hook:**

```python
import contextlib
import psycopg_pool
from collections import abc

type PoolType = psycopg_pool.AsyncConnectionPool


@contextlib.asynccontextmanager
async def postgres_lifespan() -> abc.AsyncIterator[PoolType]:
    """
    Set up PostgreSQL connection pool.

    Yields the pool after opening connections. Automatically closes
    the pool on application shutdown.
    """
    async with psycopg_pool.AsyncConnectionPool(
            conninfo='postgresql://user:pass@localhost/db',
            min_size=2,
            max_size=10,
    ) as pool:
        await pool.open(wait=True)
        yield pool
```

**Redis lifespan hook:**

```python
import redis.asyncio as redis

type RedisClientType = redis.Redis


@contextlib.asynccontextmanager
async def redis_lifespan() -> abc.AsyncIterator[RedisClientType]:
    """
    Set up Redis client.

    Yields the client after connection. Automatically closes
    the connection on application shutdown.
    """
    client = redis.Redis(
        host='localhost', port=6379, db=0, decode_responses=True
    )
    try:
        await client.ping()  # Verify connection
        yield client
    finally:
        await client.aclose()
```

**Key points:**

- Hooks are decorated with `@contextlib.asynccontextmanager`
- They yield exactly one value (the resource to inject)
- They handle their own cleanup in the finally block or via context
  manager
- Type hints on the return value (`AsyncIterator[PoolType]`) enable type
  preservation

### Step 2: Combine Hooks

Create a `Lifespan` instance that combines all your hooks:

```python
import fastapi
from imbi_gateway import lifespan

app = fastapi.FastAPI(
    lifespan=lifespan.Lifespan(postgres_lifespan, redis_lifespan)
)
```

**What happens internally:**

1. On application startup, `Lifespan.__call__()` is invoked
2. Each hook is entered via `AsyncExitStack.enter_async_context(hook())`
3. The yielded resource is stored in a `dict[LifespanHook, object]`
4. Duplicate hooks are detected and only executed once
5. On shutdown, resources are cleaned up in LIFO order
   (last-in-first-out)

### Step 3: Create Dependency Injection Functions

These functions retrieve resources from the lifespan context and prepare
them for use in route handlers.

**PostgreSQL dependency injection:**

```python
import typing
import psycopg

type CursorType = psycopg.AsyncCursor[tuple[typing.Any, ...]]


async def _get_postgres_cursor(
        context: lifespan.InjectLifespan
) -> abc.AsyncIterator[CursorType]:
    """
    Provide a PostgreSQL cursor for the request.

    Retrieves the connection pool from lifespan state, acquires a
    connection, creates a cursor, and yields it. Automatically commits
    on success or rolls back on error.
    """
    pool = context.get_state(postgres_lifespan)
    async with pool.connection() as conn:
        async with conn.cursor() as cursor:
            yield cursor
```

**Redis dependency injection:**

```python
def _get_redis_client(
        context: lifespan.InjectLifespan
) -> RedisClientType:
    """
    Provide the Redis client for the request.

    Retrieves the Redis client from lifespan state. The client is
    shared across all requests and managed by the lifespan.
    """
    return context.get_state(redis_lifespan)
```

**Key points:**

- Functions accept `InjectLifespan` as a parameter (provided by FastAPI)
- They call `context.get_state(hook)` to retrieve the resource
- **Type preservation:** `get_state()` returns the exact type yielded by
  the hook
- Functions can return resources directly or yield them (for per-request
  setup/cleanup)
- Async generators enable per-request resource acquisition (like
  connections)

### Step 4: Define Type Aliases

Create type aliases that combine the resource type with the dependency
injection function:

```python
PostgresCursor = typing.Annotated[
    CursorType, fastapi.Depends(_get_postgres_cursor)
]

RedisClient = typing.Annotated[
    RedisClientType, fastapi.Depends(_get_redis_client)
]
```

**What this does:**

- `Annotated[T, Depends(func)]` tells FastAPI to call `func` to resolve
  the parameter
- Type checkers see the first argument (`CursorType`, `RedisClientType`)
  as the actual type
- IDEs provide autocomplete based on the actual resource type
- Route handlers declare dependencies using these aliases

### Step 5: Use in Route Handlers

Now you can use your resources in route handlers with full type safety:

```python
@app.get('/users/{user_id}')
async def get_user(
        user_id: int,
        *,
        cursor: PostgresCursor,
        redis: RedisClient,
) -> dict[str, typing.Any]:
    """
    Fetch user data from PostgreSQL and cache in Redis.
    """
    # Check Redis cache first
    cached = await redis.get(f'user:{user_id}')
    if cached:
        return {'source': 'cache', 'data': cached}

    # Query PostgreSQL
    await cursor.execute(
        'SELECT id, name, email FROM users WHERE id = %s',
        (user_id,)
    )
    row = await cursor.fetchone()
    if not row:
        raise fastapi.HTTPException(404, 'User not found')

    user_data = {'id': row[0], 'name': row[1], 'email': row[2]}

    # Cache in Redis
    await redis.setex(
        f'user:{user_id}', 3600, str(user_data)
    )

    return {'source': 'database', 'data': user_data}
```

**Benefits:**

- `cursor` has type `CursorType` with full IDE autocomplete
- `redis` has type `RedisClientType` with full IDE autocomplete
- Type checkers verify method calls and parameters at compile time
- FastAPI automatically resolves dependencies before calling the handler
- If a required hook is missing, you get an HTTP 500 error with a clear
  message

### Testing Your Lifespan Hooks

Test hooks independently using `unittest.IsolatedAsyncioTestCase`:

```python
import unittest
from imbi_gateway import lifespan


class LifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_postgres_hook(self) -> None:
        """Test PostgreSQL hook setup and teardown."""
        async with postgres_lifespan() as pool:
            self.assertIsInstance(pool, psycopg_pool.AsyncConnectionPool)
            # Verify pool is open
            async with pool.connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute('SELECT 1')
                    result = await cursor.fetchone()
                    self.assertEqual(result, (1,))

    async def test_combined_lifespan(self) -> None:
        """Test Lifespan with multiple hooks."""
        func = lifespan.Lifespan(postgres_lifespan, redis_lifespan)
        async with func(fastapi.FastAPI()) as result:
            lifespan_data = result['lifespan_data']

            # Verify both resources are available
            pool = lifespan_data.get_state(postgres_lifespan)
            redis = lifespan_data.get_state(redis_lifespan)

            self.assertIsInstance(pool, psycopg_pool.AsyncConnectionPool)
            self.assertIsInstance(redis, redis.Redis)
```

For integration tests with the full application, use
`fastapi.testclient.TestClient`:

```python
def test_route_handler(self) -> None:
    """Test route handler with injected dependencies."""
    app = fastapi.FastAPI(
        lifespan=lifespan.Lifespan(postgres_lifespan, redis_lifespan)
    )
    app.add_api_route('/users/{user_id}', get_user)

    with fastapi.testclient.TestClient(app) as client:
        response = client.get('/users/1')
        self.assertEqual(response.status_code, 200)
        self.assertIn('data', response.json())
```

See `tests/test_lifespan.py` for 10 complete test cases covering edge
cases like missing hooks, duplicate hooks, and error handling.

## API Reference

### Type Aliases

#### `LifespanHook`

```python
type LifespanHook = abc.Callable[
    [], contextlib.AbstractAsyncContextManager[object | None]
]
```

A callable that returns an async context manager yielding a resource or
`None`. This is the base type for lifespan hooks.

**Example:**

```python
@contextlib.asynccontextmanager
async def my_hook() -> abc.AsyncIterator[MyResource]:
    resource = MyResource()
    await resource.connect()
    yield resource
    await resource.disconnect()
```

#### `TypedLifespanHook[T]`

```python
type TypedLifespanHook[T] = abc.Callable[
    [], contextlib.AbstractAsyncContextManager[T | None]
]
```

A generic version of `LifespanHook` that preserves the resource type `T`.
Used by `get_state()` to enable type-safe resource retrieval.

**Example:**

```python
# postgres_lifespan is TypedLifespanHook[PoolType]
async def postgres_lifespan() -> abc.AsyncIterator[PoolType]:
    ...


# get_state() knows the return type is PoolType
pool = context.get_state(postgres_lifespan)  # pool: PoolType
```

#### `InjectLifespan`

```python
InjectLifespan: t.TypeAlias = t.Annotated[
    Lifespan, fastapi.Depends(_get_lifespan)
]
```

Type alias for injecting the `Lifespan` instance into dependency
functions. Use this as the parameter type in your dependency injection
functions.

**Example:**

```python
def _get_my_resource(context: InjectLifespan) -> MyResource:
    return context.get_state(my_resource_hook)
```

### `Lifespan` Class

#### `__init__(self, *hooks: LifespanHook) -> None`

Create a `Lifespan` instance that combines multiple hooks.

**Parameters:**

- `*hooks`: Variable number of lifespan hooks to combine

**Behavior:**

- Hooks are stored in the order provided
- Duplicate hooks are deduplicated (same hook only runs once)
- Hooks are entered in the order provided
- Hooks are exited in LIFO order (last-in-first-out)

**Example:**

```python
app = fastapi.FastAPI(
    lifespan=lifespan.Lifespan(
        postgres_lifespan,
        redis_lifespan,
        metrics_lifespan,
    )
)
```

#### `get_state[T](self, hook: TypedLifespanHook[T]) -> T`

Retrieve the resource yielded by a specific hook.

**Parameters:**

- `hook`: The lifespan hook whose resource to retrieve

**Returns:**

The resource yielded by the hook, with type preserved

**Raises:**

- `fastapi.HTTPException(500)`: If the hook was not registered or
  lifespan hasn't been initialized

**Example:**

```python
def _get_resource(context: InjectLifespan) -> MyResource:
    # Type of resource is MyResource (not object)
    resource = context.get_state(my_resource_hook)
    return resource
```

#### `__call__(self, _app: FastAPI) -> AbstractAsyncContextManager[...]`

Make the `Lifespan` instance callable as a FastAPI lifespan function.
This is called automatically by FastAPI during application startup.

**Parameters:**

- `_app`: The FastAPI application (unused, required by FastAPI protocol)

**Returns:**

An async context manager that yields `{'lifespan_data': self}`

**Behavior:**

1. On entry, enters each hook via `AsyncExitStack`
2. Stores `hook → resource` mappings in the instance
3. Yields the lifespan data to FastAPI
4. On exit, cleans up resources in LIFO order

**Example:**

```python
# Called automatically by FastAPI
app = fastapi.FastAPI(lifespan=Lifespan(hook1, hook2))
```

## Advanced Topics

### Hook Deduplication

If the same hook is passed multiple times, it only executes once:

```python
lifespan.Lifespan(postgres_lifespan, postgres_lifespan)
# postgres_lifespan only runs once
```

**Implementation:**

```python
# In __call__
for hook in self._hooks:
    if hook not in self:  # Check if already entered
        self[hook] = await stack.enter_async_context(hook())
```

This enables patterns like:

```python
# Both features need postgres, but it only initializes once
app = fastapi.FastAPI(
    lifespan=lifespan.Lifespan(
        *feature_a_hooks(),  # Includes postgres_lifespan
        *feature_b_hooks(),  # Also includes postgres_lifespan
    )
)
```

### Error Handling

**Missing hook at runtime:**

```python
def _get_resource(context: InjectLifespan) -> MyResource:
    return context.get_state(my_hook)  # Hook not in Lifespan()
```

Result: HTTP 500 with detail message:
`Unmet lifespan dependency hook <function my_hook at 0x...>`

**Lifespan not initialized:**

```python
# Forgot to pass lifespan to FastAPI
app = fastapi.FastAPI()  # No lifespan parameter


@app.get('/')
def handler(*, resource: MyResource) -> None:
    ...
```

Result: HTTP 500 with detail message: `Lifespan not available`

**Hook raises exception during setup:**

If a hook raises an exception during `__aenter__`, the exception
propagates and the application fails to start. Previously entered hooks
are automatically cleaned up by `AsyncExitStack`.

**Hook raises exception during teardown:**

If a hook raises an exception during `__aexit__`, the exception is logged
but doesn't prevent other hooks from cleaning up (thanks to
`AsyncExitStack`).

### Resource Cleanup Order

Resources are cleaned up in LIFO order (last-in-first-out), the reverse
of initialization order:

```python
lifespan.Lifespan(postgres_lifespan, redis_lifespan, metrics_lifespan)
```

**Initialization order:**

1. `postgres_lifespan` enters
2. `redis_lifespan` enters
3. `metrics_lifespan` enters

**Cleanup order:**

1. `metrics_lifespan` exits
2. `redis_lifespan` exits
3. `postgres_lifespan` exits

This is important when hooks depend on each other. For example, if
metrics need to record stats during other hooks' cleanup, initialize
metrics last so it cleans up first.

### Testing Patterns

**Test hooks in isolation:**

```python
async def test_hook_lifecycle(self) -> None:
    async with my_hook() as resource:
        # Verify resource is initialized
        self.assertIsNotNone(resource)
        # Use resource
        ...
    # Verify resource is cleaned up (if observable)
```

**Test combined lifespan:**

```python
async def test_multiple_hooks(self) -> None:
    func = lifespan.Lifespan(hook1, hook2)
    async with func(fastapi.FastAPI()) as result:
        data = result['lifespan_data']
        resource1 = data.get_state(hook1)
        resource2 = data.get_state(hook2)
        # Verify both resources available
```

**Test route handlers with mocked resources:**

```python
def test_handler_with_mock(self) -> None:
    @contextlib.asynccontextmanager
    async def mock_hook() -> abc.AsyncIterator[MockResource]:
        yield MockResource()

    app = fastapi.FastAPI(lifespan=lifespan.Lifespan(mock_hook))
    # Test with mock resource
```

**Test error conditions:**

```python
def test_missing_hook_error(self) -> None:
    # Create app without the required hook
    app = fastapi.FastAPI(lifespan=lifespan.Lifespan())

    @app.get('/')
    def handler(*, res: MyResource) -> None:
        ...

    with fastapi.testclient.TestClient(app) as client:
        response = client.get('/')
        self.assertEqual(500, response.status_code)
```

## Design Rationale

### Why Not Multiple Lifespans?

FastAPI's lifespan parameter accepts a single callable because:

1. **Simplicity:** One entry point for all application-level setup
2. **Order control:** Explicit control over initialization/cleanup order
3. **State sharing:** Single context for passing state to the application

The `Lifespan` class embraces this design while enabling composition.

### Type Safety Considerations

**Why use `TypedLifespanHook[T]` instead of just `LifespanHook`?**

Without generics, `get_state()` would return `object | None`:

```python
# Without TypedLifespanHook[T]
def get_state(self, hook: LifespanHook) -> object | None:
    return self[hook]


# Usage requires manual casting
pool = t.cast(PoolType, context.get_state(postgres_lifespan))
```

With generics, the return type is inferred:

```python
# With TypedLifespanHook[T]
def get_state[T](self, hook: TypedLifespanHook[T]) -> T:
    return t.cast('T', self[hook])


# No casting needed, type is inferred
pool = context.get_state(postgres_lifespan)  # pool: PoolType
```

**How does type inference work?**

When you define a hook:

```python
async def postgres_lifespan() -> abc.AsyncIterator[PoolType]:
    ...
```

The type checker infers `postgres_lifespan` has type
`TypedLifespanHook[PoolType]`. When you call
`context.get_state(postgres_lifespan)`, the generic `T` is bound to
`PoolType`, so the return type is `PoolType`.

### Alternative Approaches Considered

**Option 1: String-based keys**

```python
# Rejected: No type safety, prone to typos
pool = request.state.postgres_pool  # What type is this?
```

**Option 2: Class-based resources**

```python
# Rejected: Requires base class, less flexible
class PostgresResource(LifespanResource):
    ...
```

**Option 3: Global singletons**

```python
# Rejected: Hard to test, implicit dependencies
POSTGRES_POOL = None  # Global state is bad
```

**Option 4: Dependency injection framework**

```python
# Rejected: FastAPI already has Depends(), don't reinvent
```

The chosen approach leverages FastAPI's existing `Depends()` mechanism
while adding type-safe composition.

## Troubleshooting

### Common Errors

#### Error: `Unmet lifespan dependency hook <function ...>`

**Cause:** You're calling `get_state(hook)` with a hook that wasn't
passed to `Lifespan()`.

**Fix:** Add the hook to the `Lifespan` constructor:

```python
# Before
app = fastapi.FastAPI(lifespan=lifespan.Lifespan(postgres_lifespan))

# After
app = fastapi.FastAPI(
    lifespan=lifespan.Lifespan(postgres_lifespan, redis_lifespan)
)
```

#### Error: `Lifespan not available`

**Cause:** The FastAPI application wasn't configured with a lifespan, or
you're trying to access lifespan data outside a request context.

**Fix:** Ensure you pass the `lifespan` parameter when creating the app:

```python
app = fastapi.FastAPI(lifespan=lifespan.Lifespan(...))
```

#### Type checker error:

`Argument of type "(...) -> AsyncIterator[...]" cannot be assigned to parameter "hook" of type "TypedLifespanHook[T@get_state]"`

**Cause:** The hook function's return type annotation is missing or
incorrect.

**Fix:** Ensure your hook has a proper type annotation:

```python
# Wrong: No return type
@contextlib.asynccontextmanager
async def my_hook():
    yield MyResource()


# Correct: Full return type
@contextlib.asynccontextmanager
async def my_hook() -> abc.AsyncIterator[MyResource]:
    yield MyResource()
```

#### Hook executes multiple times

**Cause:** You're calling the hook function (with `()`) instead of
passing the function reference.

**Fix:** Pass the function itself, not a call to it:

```python
# Wrong: Calling the hook
lifespan.Lifespan(postgres_lifespan())

# Correct: Passing the hook function
lifespan.Lifespan(postgres_lifespan)
```

### Debug Techniques

**Print lifespan state:**

```python
def _get_resource(context: InjectLifespan) -> MyResource:
    print(f'Available hooks: {list(context.keys())}')
    return context.get_state(my_hook)
```

**Check if hook is registered:**

```python
def _get_resource(context: InjectLifespan) -> MyResource:
    if my_hook not in context:
        raise ValueError(f'Hook {my_hook} not registered')
    return context.get_state(my_hook)
```

**Test hook in isolation:**

```python
async def test_hook() -> None:
    async with my_hook() as resource:
        print(f'Resource: {resource}')
        print(f'Type: {type(resource)}')
```

**Verify hook order:**

```python
calls: list[str] = []


@contextlib.asynccontextmanager
async def hook1() -> abc.AsyncIterator[None]:
    calls.append('hook1 enter')
    yield
    calls.append('hook1 exit')


@contextlib.asynccontextmanager
async def hook2() -> abc.AsyncIterator[None]:
    calls.append('hook2 enter')
    yield
    calls.append('hook2 exit')


# After running app
print(calls)  # ['hook1 enter', 'hook2 enter', 'hook2 exit', 'hook1 exit']
```

---

**See Also:**

- `src/imbi_gateway/lifespan.py` - Implementation and module docstring
- `tests/test_lifespan.py` - Complete test suite with examples
- `AGENTS.md` - Quick reference for AI assistants

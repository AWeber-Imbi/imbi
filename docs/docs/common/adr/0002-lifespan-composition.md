# ADR 0002: Lifespan Composition via Hook-Keyed State

## Status

Accepted

## Context

FastAPI's `lifespan` parameter accepts a single callable. A production
service typically needs several application-scoped resources—a database
connection pool, a Redis client, an outbound HTTP client—each with
independent setup and teardown logic.

The naive workaround is a hand-written combined context manager:

```python
@contextlib.asynccontextmanager
async def combined_lifespan(app):
    async with postgres_pool() as pool:
        async with redis_client() as redis:
            yield {'pool': pool, 'redis': redis}
```

This works but has several drawbacks:

- **Type erasure**: the yielded `dict[str, object]` loses the specific
  types, so every call site must cast or annotate manually.
- **String coupling**: route handlers reference resources by string key
  (`request.state.pool`), with no compiler-checked contract.
- **Tight composition**: adding a resource means editing the combined
  function, creating a single choke point.
- **Deduplication is manual**: if two feature modules both need Postgres,
  the combined function must track that and avoid entering the context
  manager twice.

We need a reusable composition mechanism that: preserves types through
FastAPI's dependency injection system, keeps each hook independent, and
does not require central coordination when new resources are added.

## Decision

### 1. Represent the lifespan as a `dict` subclass keyed by hook function

`Lifespan` extends `dict[LifespanHook, object | None]`, where
`LifespanHook` is the *function itself*. The function identity serves as
the key.

**Rationale**: Python functions are hashable singletons. Using the
function as the key means no separate registry is needed, deduplication
is a single `hook not in self` check, and—crucially—the key is also the
type carrier (see decision 2 below).

### 2. Use generic `get_state[T]` with `TypedLifespanHook[T]` to preserve types

```python
type TypedLifespanHook[T] = abc.Callable[
    [], contextlib.AbstractAsyncContextManager[T | None]
]

def get_state[T](self, hook: TypedLifespanHook[T]) -> T: ...
```

When a hook is annotated as `async def my_hook() -> AsyncIterator[Pool]`,
the type checker infers it as `TypedLifespanHook[Pool]`. Passing it to
`get_state()` binds `T = Pool`, so the return type is `Pool` — no cast
required at any call site.

**Rationale**: Thread the type information through the hook function
itself rather than through a separate registry or a string key. The
function that *produces* the resource also *names* its type, so the
same object carries both roles.

### 3. Clean up via `AsyncExitStack` in LIFO order

`Lifespan.__call__` uses `contextlib.AsyncExitStack` to enter each hook.
The stack unwinds in last-in-first-out order, matching the invariant that
a resource should outlive anything that depends on it.

**Rationale**: `AsyncExitStack` handles exception propagation correctly
across multiple context managers without manual try/finally nesting. LIFO
cleanup order is the conventional and safest default; callers control the
order by the sequence they pass to `Lifespan(...)`.

### 4. Expose the lifespan instance through a module-level `InjectLifespan` alias

```python
type InjectLifespan = t.Annotated[Lifespan, fastapi.Depends(_get_lifespan)]
```

DI functions declare `context: InjectLifespan` as their only parameter.
FastAPI resolves it to the `Lifespan` stored in `request.state`.

**Rationale**: Consumers never import `_get_lifespan` or `Lifespan`
directly into their parameter lists. The `Annotated` alias keeps the
FastAPI wiring invisible while leaving the type visible to static
analysis.

## Alternatives Considered

**String-keyed `request.state` dictionary**

Accessing `request.state.postgres` directly. Rejected because there is
no compile-time contract: typos silently produce `AttributeError` at
runtime, and the types of the values are unknown to the type checker.

**Class-based resource registry**

A base class `LifespanResource` that each resource extends. Rejected
because it requires every resource to opt in to a base class, adding
coupling to the resource implementations, and still does not restore type
information at DI call sites without a generic accessor.

**Global singletons**

Module-level variables set during startup. Rejected because they make
tests harder to isolate (shared mutable global state) and make dependency
relationships implicit.

**Third-party DI framework**

Libraries such as `dependency-injector` or `punq`. Rejected because
FastAPI already provides `Depends()`, and adding a parallel DI container
would create two overlapping systems to reason about.

**Separate `request.state` key per resource**

Each hook stores its result under a unique string key in `app.state`.
Rejected for the same reason as the string-keyed dictionary: no type
safety, no deduplication contract, and coupling between the hook and
every consumer via the shared string.

## Consequences

### Positive

- **Type safety end-to-end**: IDEs and type checkers track the resource
  type from the hook definition through `get_state()` into the route
  handler parameter.
- **Independent hooks**: each resource's lifecycle is encapsulated in its
  own function; the `Lifespan` constructor is the only place they meet.
- **Automatic deduplication**: shared hooks (e.g., a database pool
  needed by multiple feature modules) run exactly once regardless of
  how many times they appear in the constructor arguments.
- **Testable in isolation**: hooks are plain async context managers and
  can be entered directly in unit tests without spinning up a FastAPI app.
- **Extensible**: adding a new resource requires no changes to existing
  hooks or to the `Lifespan` class itself.

### Negative

- **FastAPI coupling**: the module imports `fastapi` and raises
  `HTTPException` on error, making it unsuitable for non-FastAPI
  applications without modification.
- **Hook identity as key**: if a hook function is re-created (e.g., via
  `functools.partial` or a factory), each call produces a distinct key.
  Callers must store and reuse the same function object.
- **Opaque errors for missing hooks**: a missing hook surfaces as an
  HTTP 500 at request time rather than a startup failure. This is
  intentional (hooks are resolved lazily through DI), but means
  misconfiguration is not caught until the first request exercises the
  relevant dependency path.

## References

- `src/imbi_common/lifespan.py` — implementation
- `tests/test_lifespan.py` — test suite
- [ADR 0001](0001-imbi-common-library-extraction.md) — decision to keep
  FastAPI-specific code out of the common library (lifespan is an
  exception: it provides purely structural plumbing with no
  domain logic)

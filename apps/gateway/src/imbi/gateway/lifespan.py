"""FastAPI lifespan composition with type-safe dependency injection.

Problem:
    FastAPI accepts only one lifespan callable, but applications need
    multiple independent resources (database pools, Redis connections)
    with separate setup/teardown lifecycles.

Solution:
    The Lifespan class composes multiple async context managers into a
    single lifespan while preserving type information through dependency
    injection.

Quick Example:
    ::

        @contextlib.asynccontextmanager
        async def postgres_lifespan() -> abc.AsyncIterator[PoolType]:
            async with psycopg_pool.AsyncConnectionPool(...) as pool:
                yield pool

        async def _inject_pool(
            context: InjectLifespan
        ) -> abc.AsyncIterator[PoolType]:
            pool = context.get_state(postgres_lifespan)
            async with pool.connection() as conn:
                yield conn

        PostgresPool = t.Annotated[
            PoolType, fastapi.Depends(_inject_pool)
        ]

        app = fastapi.FastAPI(lifespan=Lifespan(postgres_lifespan))

        @app.get('/')
        async def handler(*, pool: PostgresPool) -> None:
            ...

Usage Pattern:
    1. Define lifespan hooks as async context managers returning
       resources
    2. Create Lifespan instance combining all hooks
    3. Define dependency injection functions using get_state()
    4. Create type aliases with Annotated[T, Depends(...)]
    5. Use type aliases in route handler parameters

See Also:
    - tests/test_lifespan.py for complete examples and edge cases
    - AGENTS.md for AI assistant guidance on applying this pattern
    - docs/lifespan-pattern.md for comprehensive reference documentation
"""

import contextlib
import http
import typing as t
from collections import abc

import fastapi
import imbi_common.helpers

type LifespanHook = abc.Callable[
    [], contextlib.AbstractAsyncContextManager[object | None]
]
type RequestState = abc.Mapping[str, object | None]
type TypedLifespanHook[T] = abc.Callable[
    [], contextlib.AbstractAsyncContextManager[T | None]
]


class Lifespan(dict[LifespanHook, object | None]):
    """Compose multiple lifespan hooks into a single FastAPI lifespan.

    Manages multiple independent async context managers (lifespan hooks)
    and provides type-safe access to their yielded resources through
    dependency injection. Hooks are deduplicated (same hook only runs
    once) and cleaned up in LIFO order.

    Args:
        *hooks (LifespanHook): Variable number of lifespan hooks to
            combine. Each hook is an async context manager that yields
            a resource.

    Example:
        ::

            @contextlib.asynccontextmanager
            async def postgres_lifespan() -> abc.AsyncIterator[PoolType]:
                async with psycopg_pool.AsyncConnectionPool(...) as pool:
                    yield pool

            app = fastapi.FastAPI(
                lifespan=Lifespan(postgres_lifespan, redis_lifespan)
            )

    See Also:
        get_state: Retrieve resources from hooks with type preservation
        InjectLifespan: Type alias for dependency injection
    """

    def __init__(self, *hooks: LifespanHook) -> None:
        """Initialize Lifespan with the given hooks.

        Args:
            *hooks (LifespanHook): Variable number of lifespan hooks to
                combine. Hooks are entered in the order provided and
                exited in LIFO order. Duplicate hooks are deduplicated
                automatically.
        """
        super().__init__()
        self._hooks: tuple[LifespanHook, ...] = hooks

    def get_state[T](self, hook: TypedLifespanHook[T]) -> T:
        """Retrieve the resource yielded by a specific hook.

        This is a generic method that preserves type information. If the
        hook yields a resource of type `T`, this method returns `T`.

        Args:
            hook (TypedLifespanHook[T]): The lifespan hook whose
                resource to retrieve. Must have been passed to the
                Lifespan constructor.

        Returns:
            T: The resource yielded by the hook, with type preserved.

        Raises:
            fastapi.HTTPException: 500 error if the hook was not
                registered with this Lifespan instance.

        Example:
            ::

                def _inject_pool(context: InjectLifespan) -> PoolType:
                    # Type of pool is PoolType (not object)
                    pool = context.get_state(postgres_lifespan)
                    return pool
        """
        try:
            return t.cast('T', self[hook])
        except KeyError:
            raise fastapi.HTTPException(
                http.HTTPStatus.INTERNAL_SERVER_ERROR,
                detail=f'Unmet lifespan dependency hook {hook!r}',
            ) from None

    def __call__(
        self, _app: fastapi.FastAPI
    ) -> contextlib.AbstractAsyncContextManager[dict[str, 'Lifespan']]:
        """Make Lifespan callable as a FastAPI lifespan function.

        This method is called automatically by FastAPI during application
        startup. It enters all registered hooks, stores their yielded
        resources, and ensures proper cleanup on shutdown.

        Args:
            _app (fastapi.FastAPI): The FastAPI application instance
                (unused, required by FastAPI lifespan protocol).

        Returns:
            contextlib.AbstractAsyncContextManager[dict[str, Lifespan]]:
                An async context manager that yields a dictionary
                containing the Lifespan instance under the key
                'lifespan_data'.

        Note:
            - Hooks are entered in the order provided to __init__
            - Duplicate hooks are detected and only executed once
            - Resources are cleaned up in LIFO order (last-in-first-out)
            - Uses AsyncExitStack to ensure proper cleanup even if hooks
              raise exceptions
        """

        @contextlib.asynccontextmanager
        async def cm() -> abc.AsyncIterator[dict[str, 'Lifespan']]:
            async with contextlib.AsyncExitStack() as stack:
                for hook in self._hooks:
                    if hook not in self:
                        self[hook] = await stack.enter_async_context(hook())
                yield {'lifespan_data': self}

        return cm()


def _get_lifespan(request: fastapi.Request) -> Lifespan:
    """Extract the Lifespan instance from request state.

    This is a FastAPI dependency function that retrieves the Lifespan
    instance from the request state. Used internally by InjectLifespan.

    Args:
        request (fastapi.Request): The current request object.

    Returns:
        Lifespan: The Lifespan instance that was set up during
            application startup.

    Raises:
        fastapi.HTTPException: 500 error if the lifespan was not
            initialized (missing lifespan parameter in FastAPI()
            constructor) or if request.state.lifespan_data is not
            accessible.

    See Also:
        InjectLifespan: Type alias that uses this function via Depends()
    """
    try:
        return imbi_common.helpers.unwrap_as(
            Lifespan, t.cast('object', request.state.lifespan_data)
        )
    except AttributeError:
        raise fastapi.HTTPException(
            http.HTTPStatus.INTERNAL_SERVER_ERROR,
            detail='Lifespan not available',
        ) from None


InjectLifespan: t.TypeAlias = t.Annotated[
    Lifespan, fastapi.Depends(_get_lifespan)
]

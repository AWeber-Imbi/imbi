import contextlib
import datetime
import http
import typing
import unittest
from collections import abc

import fastapi.testclient
from imbi_common import lifespan


class LifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_lifespan(self) -> None:
        func = lifespan.Lifespan()
        async with func(fastapi.FastAPI()) as result:
            self.assertEqual(result, {'lifespan_data': {}})

    async def test_lifespan_with_hooks(self) -> None:
        calls: set[str] = set()

        @contextlib.asynccontextmanager
        async def hook() -> abc.AsyncIterator[None]:
            calls.add('hook')
            yield

        @contextlib.asynccontextmanager
        async def other_hook() -> abc.AsyncIterator[list[int]]:
            calls.add('other_hook')
            yield [1, 2, 3]

        func = lifespan.Lifespan(hook, other_hook)
        async with func(fastapi.FastAPI()) as result:
            self.assertEqual(
                result, {'lifespan_data': {hook: None, other_hook: [1, 2, 3]}}
            )
        self.assertSetEqual({'hook', 'other_hook'}, calls)

    def test_object_lifespan_data(self) -> None:
        class HookState:
            def __init__(self) -> None:
                self.data = ['hello', 'world']

        @contextlib.asynccontextmanager
        async def hook() -> abc.AsyncIterator[HookState]:
            yield HookState()

        def _inject_hook(context: lifespan.InjectLifespan) -> HookState:
            return context.get_state(hook)

        def request_handler(
            *,
            state: typing.Annotated[HookState, fastapi.Depends(_inject_hook)],
        ) -> list[str]:
            return state.data

        app = fastapi.FastAPI(lifespan=lifespan.Lifespan(hook))
        app.add_api_route('/', request_handler)

        with fastapi.testclient.TestClient(app) as client:
            response = client.get('/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(['hello', 'world'], response.json())

    async def test_primitive_lifespan_data(self) -> None:
        state_value = 'whatever'

        @contextlib.asynccontextmanager
        async def hook() -> abc.AsyncIterator[str]:
            yield state_value

        def _inject_hook(context: lifespan.InjectLifespan) -> str:
            return context.get_state(hook)

        def request_handler(
            *, state: typing.Annotated[str, fastapi.Depends(_inject_hook)]
        ) -> str:
            return state

        app = fastapi.FastAPI(lifespan=lifespan.Lifespan(hook))
        app.add_api_route('/', request_handler)

        with fastapi.testclient.TestClient(app) as client:
            response = client.get('/')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(state_value, response.json())

    def test_lifespan_with_none_state(self) -> None:
        @contextlib.asynccontextmanager
        async def hook() -> abc.AsyncIterator[None]:
            yield None

        def _inject_hook(context: lifespan.InjectLifespan) -> None:
            return context.get_state(hook)  # type: ignore[return-value]

        app = fastapi.FastAPI(lifespan=lifespan.Lifespan(hook))

        @app.get('/')
        def request_handler(
            *, state: typing.Annotated[None, fastapi.Depends(_inject_hook)]
        ) -> None:
            return state

        with fastapi.testclient.TestClient(app) as client:
            response = client.get('/')
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(response.json())

    def test_multiple_states(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        structured: dict[str, object] = {
            'number': 42,
            'string': 'whatever',
            'list': ['hello', 'world'],
        }

        @contextlib.asynccontextmanager
        async def now_hook() -> abc.AsyncIterator[datetime.datetime]:
            yield now

        def _inject_now(context: lifespan.InjectLifespan) -> datetime.datetime:
            return context.get_state(now_hook)

        @contextlib.asynccontextmanager
        async def structured_hook() -> abc.AsyncIterator[dict[str, object]]:
            yield structured

        def _inject_structured(
            context: lifespan.InjectLifespan,
        ) -> dict[str, object]:
            return context.get_state(structured_hook)

        app = fastapi.FastAPI(
            lifespan=lifespan.Lifespan(now_hook, structured_hook)
        )

        @app.get('/now')
        def now_handler(
            *,
            now: typing.Annotated[
                datetime.datetime, fastapi.Depends(_inject_now)
            ],
        ) -> datetime.datetime:
            return now

        @app.get('/structured')
        def structured_handler(
            *,
            structured: typing.Annotated[
                dict[str, object], fastapi.Depends(_inject_structured)
            ],
        ) -> dict[str, object]:
            return structured

        with fastapi.testclient.TestClient(app) as client:
            response = client.get('/now')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'), response.json()
            )

            response = client.get('/structured')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(structured, response.json())

    async def test_lifespan_with_duplicated_states(self) -> None:
        now = datetime.datetime.now(datetime.timezone.utc)
        now_hook_call_count = 0

        @contextlib.asynccontextmanager
        async def now_hook() -> abc.AsyncIterator[datetime.datetime]:
            nonlocal now_hook_call_count
            now_hook_call_count += 1
            yield now

        func = lifespan.Lifespan(now_hook, now_hook)
        async with func(fastapi.FastAPI()) as result:
            self.assertEqual(result, {'lifespan_data': {now_hook: now}})
        self.assertEqual(now_hook_call_count, 1)

    def test_lifespan_with_invalid_hook_name(self) -> None:
        @contextlib.asynccontextmanager
        async def hook() -> abc.AsyncIterator[None]:
            yield None

        def _inject_hook(context: lifespan.InjectLifespan) -> None:
            return context.get_state(hook)  # type: ignore[return-value]

        app = fastapi.FastAPI(lifespan=lifespan.Lifespan())

        @app.get('/')
        def request_handler(
            *,
            state: typing.Annotated[str, fastapi.Depends(_inject_hook)],
        ) -> str:
            return state

        with fastapi.testclient.TestClient(app) as client:
            response = client.get('/')
            self.assertEqual(500, response.status_code)

    def test_unstarted_lifespan(self) -> None:
        @contextlib.asynccontextmanager
        async def hook() -> abc.AsyncIterator[str]:
            yield 'whatever'

        def _inject_hook(context: lifespan.InjectLifespan) -> str:
            return context.get_state(hook)

        app = fastapi.FastAPI()

        @app.get('/')
        def request_handler(
            *, state: typing.Annotated[str, fastapi.Depends(_inject_hook)]
        ) -> str:
            return state

        # if the lifespan is not started, then the failure occurs
        # when the dependency is resolved at runtime.
        with fastapi.testclient.TestClient(app) as client:
            response = client.get('/')
            self.assertEqual(
                http.HTTPStatus.INTERNAL_SERVER_ERROR, response.status_code
            )

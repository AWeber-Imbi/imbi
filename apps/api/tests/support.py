"""Shared test helpers.

Building the FastAPI app via :func:`imbi.api.app.create_app` costs
~130 ms (it registers 255 routes), and the only per-test state on the
app is ``dependency_overrides``. Rebuilding it in every ``setUp`` adds
up to minutes across the suite, so share a single instance and reset
the overrides between tests instead.

Because the app is shared across every test in the process, per-test
state must be torn down reliably even when a subclass overrides
``setUp``/``tearDown`` without chaining to ``super()``. The reset is
therefore registered in :meth:`run` (via ``addCleanup``), which always
runs regardless of subclass overrides:

* ``dependency_overrides`` is cleared so mocked dependencies cannot leak
  into the next test that reuses the cached app.
* Any :class:`starlette.testclient.TestClient` stored as an instance
  attribute is closed so its portal thread/transport is not leaked.
"""

import collections.abc
import contextlib
import functools
import typing
import unittest
from unittest import mock

import fastapi
import orjson
import pydantic
from starlette import testclient

from imbi.common import clickhouse, iggy
from imbi.common.iggy import client as iggy_client
from imbi.common.plugins.base import Plugin, PluginManifest
from imbi.common.plugins.registry import RegistryEntry


@functools.cache
def shared_app() -> fastapi.FastAPI:
    """Return a process-wide :class:`fastapi.FastAPI` instance."""
    from imbi.api import app

    return app.create_app()


def registry_entry(
    manifest: PluginManifest,
    *,
    plugin_cls: type[Plugin] | None = None,
    package_name: str | None = None,
    package_version: str = '1.0.0',
) -> RegistryEntry:
    """Build a :class:`RegistryEntry` wrapping ``manifest``.

    Centralizes the throwaway-``Plugin`` fixture pattern shared across the
    endpoint tests. When ``plugin_cls`` is omitted a fresh ``Plugin``
    subclass is created and its ``manifest`` attribute set; ``package_name``
    defaults to ``imbi-plugin-<slug>``.
    """
    if plugin_cls is None:

        class _FakePlugin(Plugin):
            pass

        _FakePlugin.manifest = manifest  # type: ignore[misc]
        plugin_cls = _FakePlugin
    return RegistryEntry(
        plugin_cls=plugin_cls,
        manifest=manifest,
        package_name=package_name or f'imbi-plugin-{manifest.slug}',
        package_version=package_version,
    )


def _reset(case: unittest.TestCase, test_app: fastapi.FastAPI) -> None:
    """Clear shared-app state and close any per-test TestClient."""
    test_app.dependency_overrides.clear()
    for value in list(vars(case).values()):
        if isinstance(value, testclient.TestClient):
            value.close()


class SharedAppTestCase(unittest.TestCase):
    """Base case that reuses one app and resets per-test state.

    The reset (clearing ``dependency_overrides`` and closing any
    ``TestClient`` attributes) is registered as a cleanup so it runs even
    when subclasses override ``setUp``/``tearDown`` without calling
    ``super()``.
    """

    test_app: fastapi.FastAPI

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.test_app = shared_app()

    def run(
        self, result: unittest.result.TestResult | None = None
    ) -> unittest.result.TestResult | None:
        self.addCleanup(_reset, self, self.test_app)
        return super().run(result)


class SharedAppAsyncTestCase(unittest.IsolatedAsyncioTestCase):
    """``IsolatedAsyncioTestCase`` variant of :class:`SharedAppTestCase`."""

    test_app: fastapi.FastAPI

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.test_app = shared_app()

    def run(
        self, result: unittest.result.TestResult | None = None
    ) -> unittest.result.TestResult | None:
        self.addCleanup(_reset, self, self.test_app)
        return super().run(result)


async def _sink_payloads(
    stream: str, payloads: list[dict[str, typing.Any]]
) -> None:
    """Insert *payloads* into *stream*'s table the way the sink does."""
    lines = '\n'.join(orjson.dumps(payload).decode() for payload in payloads)
    await clickhouse.client.Clickhouse.get_instance().command(
        f'INSERT INTO {stream} FORMAT JSONEachRow\n{lines}'
    )


@contextlib.contextmanager
def sink_to_clickhouse() -> collections.abc.Generator[None]:
    """Route ``iggy.publish`` and ``publish_rows`` straight into ClickHouse.

    For tests that write through the real code and read the row back
    from the live ClickHouse ``root:services`` boots. The payload is
    what the Iggy ClickHouse sink would receive, inserted with the
    ``JSONEachRow`` format the sink uses, so the row lands as it would
    in production, only without the stream in between.
    """

    async def publish(
        stream: str,
        topic: str,
        models: list[pydantic.BaseModel],
        *,
        columns: list[str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        await _sink_payloads(
            stream, [iggy_client._payload(model, columns) for model in models]
        )

    async def publish_rows(
        stream: str,
        topic: str,
        rows: list[dict[str, typing.Any]],
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        await _sink_payloads(stream, rows)

    with (
        mock.patch.object(
            iggy, 'publish', mock.AsyncMock(side_effect=publish)
        ),
        mock.patch.object(
            iggy, 'publish_rows', mock.AsyncMock(side_effect=publish_rows)
        ),
    ):
        yield

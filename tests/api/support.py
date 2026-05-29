"""Shared test helpers.

Building the FastAPI app via :func:`imbi_api.app.create_app` costs
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

import functools
import unittest

import fastapi
from starlette import testclient


@functools.cache
def shared_app() -> fastapi.FastAPI:
    """Return a process-wide :class:`fastapi.FastAPI` instance."""
    from imbi_api import app

    return app.create_app()


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

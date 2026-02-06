import contextlib
import os
import unittest
from collections import abc


class TestCase(unittest.IsolatedAsyncioTestCase):
    @contextlib.contextmanager
    def override_environment(
        self, **overrides: str | int | None
    ) -> abc.Iterator[None]:
        saved: dict[str, str | None] = {
            key: os.environ.get(key) for key in overrides
        }
        try:
            for key, value in overrides.items():
                os.environ.pop(key, None)
                if value is not None:
                    os.environ[key] = str(value)
            yield
        finally:
            for key, value in saved.items():
                os.environ.pop(key, None)
                if value is not None:
                    os.environ[key] = value

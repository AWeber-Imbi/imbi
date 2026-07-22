import contextlib
import os
import pathlib
import unittest
from typing import TYPE_CHECKING

import dotenv

if TYPE_CHECKING:
    from collections import abc


class TestCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        # Load .env for local development; the file is not committed
        # and load_dotenv silently does nothing when it is absent.
        my_dir = pathlib.Path(__file__).parent
        env_path = my_dir.parent / '.env'
        dotenv.load_dotenv(str(env_path))

    @contextlib.contextmanager
    def override_environment(
        self, **overrides: str | int | None
    ) -> abc.Generator[None]:
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

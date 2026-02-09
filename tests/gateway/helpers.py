import contextlib
import os
import pathlib
import unittest
from collections import abc

import dotenv


class TestCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        my_dir = pathlib.Path(__file__).parent
        env_path = my_dir.parent / '.env'
        dotenv.load_dotenv(str(env_path))

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

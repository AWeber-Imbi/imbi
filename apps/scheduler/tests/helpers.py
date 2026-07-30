import contextlib
import datetime
import os
import pathlib
import typing
import unittest
import uuid

import dotenv

from imbi.scheduler import models, triggers

if typing.TYPE_CHECKING:
    from collections import abc


def build_task(**overrides: typing.Any) -> models.Task:
    """Return a valid task, overriding any field.

    Defaults to a system task on an `api` target running as the scheduler's
    service account — the shape phase 1 actually supports.

    An override that is not a `Task` field raises rather than being dropped.
    `model_validate` ignores extras by default, so `timzeone=...` would
    otherwise leave the default in place and the case would assert against a
    task it did not describe.
    """
    unknown = set(overrides) - set(models.Task.model_fields)
    if unknown:
        raise TypeError(
            f'build_task() got unexpected field(s): {sorted(unknown)}'
        )
    now = datetime.datetime(2026, 7, 28, 6, tzinfo=datetime.UTC)
    fields: dict[str, typing.Any] = {
        'id': uuid.uuid4(),
        'slug': 'nightly-recompute',
        'name': 'Nightly recompute',
        'kind': 'system',
        'trigger': triggers.CronTrigger(expression='0 6 * * *'),
        'identity': models.Identity(
            kind='service_account', subject='imbi-scheduler'
        ),
        'target': models.ApiTarget(
            method='POST', path='/scoring/recompute-all'
        ),
        'created_by': 'scheduler-tests@example.com',
        'created_at': now,
        'updated_at': now,
    }
    fields.update(overrides)
    return models.Task.model_validate(fields)


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

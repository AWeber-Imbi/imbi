import contextlib
import datetime
import os
import pathlib
import typing
import unittest
import unittest.mock
import uuid

import dotenv
import orjson
import pydantic

from imbi.common import iggy
from imbi.common.clickhouse import client as ch_client
from imbi.common.iggy import client as iggy_client
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


async def _write_rows(stream: str, rows: list[dict[str, typing.Any]]) -> None:
    """Insert `rows` into the table `stream` lands in, as the sink would."""
    lines = '\n'.join(orjson.dumps(row).decode() for row in rows)
    await ch_client.Clickhouse.get_instance().command(
        f'INSERT INTO {stream} FORMAT JSONEachRow\n{lines}'
    )


class TestCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        my_dir = pathlib.Path(__file__).parent
        env_path = my_dir.parent / '.env'
        dotenv.load_dotenv(str(env_path))

    def setUp(self) -> None:
        super().setUp()
        self.patch_iggy()

    def patch_iggy(self) -> None:
        """Route `iggy.publish` straight into ClickHouse.

        The real path is producer, Iggy server, connectors runtime, sink,
        table, and the row shows up a poll interval later. These cases
        read what they just recorded, so the fake writes the exact
        JSONEachRow payload the sink would insert, synchronously. Every
        publish is recorded in `self.published` as `(stream, topic, rows)`.
        """
        self.published: list[tuple[str, str, list[dict[str, typing.Any]]]] = []

        async def publish(
            stream: str,
            topic: str,
            models: list[pydantic.BaseModel],
            *,
            columns: list[str] | None = None,
            headers: dict[str, str] | None = None,
        ) -> None:
            rows = [iggy_client._payload(model, columns) for model in models]
            self.published.append((stream, topic, rows))
            await _write_rows(stream, rows)

        async def publish_rows(
            stream: str,
            topic: str,
            rows: list[dict[str, typing.Any]],
            *,
            headers: dict[str, str] | None = None,
        ) -> None:
            self.published.append((stream, topic, rows))
            await _write_rows(stream, rows)

        self.enterContext(
            unittest.mock.patch.object(
                iggy, 'publish', new=unittest.mock.AsyncMock(wraps=publish)
            )
        )
        self.enterContext(
            unittest.mock.patch.object(
                iggy,
                'publish_rows',
                new=unittest.mock.AsyncMock(wraps=publish_rows),
            )
        )

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

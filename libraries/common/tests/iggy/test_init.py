import pathlib
import re
import tomllib
import unittest
from unittest import mock

import pydantic

from imbi.common import clickhouse, iggy
from imbi.common.iggy import client


class SampleModel(pydantic.BaseModel):
    id: int


class TopicsTestCase(unittest.TestCase):
    def test_events_stream_carries_the_gateway_topic(self) -> None:
        # The sink configuration imbi-api serves to the connectors
        # runtime is generated from this, so a stream or topic dropped
        # here is one the ClickHouse sink stops draining.
        self.assertIn('gateway', iggy.TOPICS['events'])

    def test_every_analytics_table_has_a_stream(self) -> None:
        self.assertEqual(
            {
                'commit_drift',
                'commits',
                'document_read_events',
                'document_read_sessions',
                'document_versions',
                'email_audit',
                'events',
                'maintenance_log',
                'operations_log',
                'pull_requests',
                'release_component_batches',
                'release_components',
                'scheduler_runs',
                'score_history',
                'tags',
            },
            set(iggy.TOPICS),
        )

    def test_every_stream_has_a_clickhouse_table(self) -> None:
        # The sink inserts each stream into the table of the same name. A
        # stream with no table takes every publish and then cannot deliver
        # any of it, and nothing reaches the producer to say so --
        # `email_audit` shipped that way.
        schemata = pathlib.Path(clickhouse.__file__).parent / 'schemata.toml'
        with schemata.open('rb') as f:
            entries = tomllib.load(f).values()
        created = {
            match.group(1)
            for entry in entries
            if entry.get('enabled', True)
            for match in re.finditer(
                r'CREATE TABLE IF NOT EXISTS imbi\.(\w+)', entry['query']
            )
        }
        for stream in iggy.TOPICS:
            with self.subTest(stream=stream):
                self.assertIn(stream, created)

    def test_every_stream_has_at_least_one_topic(self) -> None:
        for stream, topics in iggy.TOPICS.items():
            with self.subTest(stream=stream):
                self.assertTrue(topics)
                self.assertEqual(len(topics), len(set(topics)))

    def test_publish_error_is_exported(self) -> None:
        self.assertIs(client.PublishError, iggy.PublishError)


class ModuleFunctionsTestCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        client.Iggy._instance = None
        self.instance = mock.AsyncMock(spec=client.Iggy)
        self.enterContext(
            mock.patch.object(
                client.Iggy, 'get_instance', return_value=self.instance
            )
        )

    async def test_initialize(self) -> None:
        self.instance.initialize.return_value = True
        self.assertTrue(await iggy.initialize())
        self.instance.initialize.assert_awaited_once_with()

    async def test_aclose(self) -> None:
        await iggy.aclose()
        self.instance.aclose.assert_awaited_once_with()

    async def test_ensure_topic(self) -> None:
        await iggy.ensure_topic('events', 'gateway')
        self.instance.ensure_topic.assert_awaited_once_with(
            'events', 'gateway'
        )

    async def test_publish(self) -> None:
        models = [SampleModel(id=1)]
        await iggy.publish(
            'events',
            'gateway',
            models,
            columns=['id'],
            headers={'producer': 'gateway'},
        )
        self.instance.publish.assert_awaited_once_with(
            'events',
            'gateway',
            models,
            columns=['id'],
            headers={'producer': 'gateway'},
        )

    async def test_publish_rows(self) -> None:
        rows = [{'id': 1}]
        await iggy.publish_rows(
            'operations_log', 'api', rows, headers={'producer': 'api'}
        )
        self.instance.publish_rows.assert_awaited_once_with(
            'operations_log', 'api', rows, headers={'producer': 'api'}
        )

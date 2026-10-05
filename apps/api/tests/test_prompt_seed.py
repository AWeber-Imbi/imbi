"""Tests for seeding the prompts Imbi ships."""

import unittest
from unittest import mock

from imbi.api.prompts import seed
from imbi.common.prompts import resolve, system


class SeedDefaultPromptsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_creates_missing_and_skips_existing(self) -> None:
        async def fetch(_db: object, namespace: str, slug: str) -> object:
            if namespace == 'imbi-slackbot':
                return object(), 3
            raise resolve.PromptNotFound(f'{namespace}/{slug}')

        insert = mock.AsyncMock()
        with (
            mock.patch.object(resolve, 'fetch_prompt', side_effect=fetch),
            mock.patch.object(seed.prompt_endpoints, 'insert_prompt', insert),
        ):
            results = await seed.seed_default_prompts(mock.AsyncMock())

        self.assertEqual(
            results,
            [
                seed.SeedResult('imbi-assistant/system', created=True),
                seed.SeedResult('imbi-slackbot/system', created=False),
            ],
        )
        insert.assert_awaited_once()
        _db, data, author = insert.await_args.args
        self.assertEqual(author, 'imbi-setup')
        self.assertEqual(
            (data.namespace, data.slug), ('imbi-assistant', 'system')
        )
        self.assertEqual(data.default_label, 'stable')
        self.assertIsNone(data.version.model)
        self.assertEqual(data.version.system, system.ASSISTANT.text())
        self.assertEqual(
            set(data.version.variable_schema), set(system.ASSISTANT.variables)
        )

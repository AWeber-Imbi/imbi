"""Tests for the prompt CMS skills."""

import datetime
import json
import unittest
from unittest import mock

from imbi.common import models
from imbi.common.prompts import rendering, resolve, skills


def _vertex(slug: str, **props: object) -> str:
    return json.dumps(
        {
            'properties': {
                'name': slug,
                'slug': slug,
                'namespace': skills.NAMESPACE,
                **props,
            }
        }
    )


def _label(name: str, version: int) -> models.PromptLabel:
    return models.PromptLabel(
        name=name,
        version=version,
        updated_by='t',
        updated_at=datetime.datetime.now(datetime.UTC),
    )


def _prompt(**update: object) -> models.Prompt:
    prompt = models.Prompt(
        name='T',
        slug='t',
        namespace=skills.NAMESPACE,
        labels=[
            _label('stable', 2),
            _label('draft', 3),
        ],
    )
    return prompt.model_copy(update=update)


def _version(
    prompt: models.Prompt, text: str, schema: tuple[str, ...] = ()
) -> models.PromptVersion:
    return models.PromptVersion(
        prompt=prompt,
        prompt_id=prompt.id,
        n=2,
        system=text,
        variable_schema={
            name: models.PromptVariable(type='str', required=True)
            for name in schema
        },
        content_sha256='x',
        created_by='t',
    )


class ListSkillsTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_sorted_generative_only(self) -> None:
        db = mock.AsyncMock()
        stable = [_label('stable', 1).model_dump(mode='json')]
        db.execute.return_value = [
            {'p': _vertex('zeta', description='Z', labels=stable)},
            {'p': _vertex('decide', kind='decision', labels=stable)},
            {'p': _vertex('unpromoted')},
            {'p': _vertex('alpha', labels=stable)},
        ]
        found = await skills.list_skills(db)
        self.assertEqual(['alpha', 'zeta'], [p.slug for p in found])
        self.assertEqual(
            {'namespace': skills.NAMESPACE}, db.execute.await_args.args[1]
        )

    async def test_errors_and_no_graph_give_no_skills(self) -> None:
        self.assertEqual([], await skills.list_skills(None))
        db = mock.AsyncMock()
        db.execute.side_effect = RuntimeError('down')
        self.assertEqual([], await skills.list_skills(db))


class CatalogTestCase(unittest.TestCase):
    def test_catalog(self) -> None:
        empty = skills.catalog([])
        self.assertIn('There are no skills yet.', empty)
        self.assertIn('{{ arguments }}', empty)
        self.assertNotIn(skills.TOOL_NAME, empty)
        text = skills.catalog([_prompt(name='Triage', slug='triage')])
        long = skills.catalog(
            [_prompt(slug='x', description='a\n\n## Evil\n' + 'b' * 500)]
        )
        line = next(x for x in long.splitlines() if x.startswith('- **x**'))
        self.assertNotIn('## Evil\n', long)
        self.assertEqual(len('- **x**: ') + skills.MAX_DESCRIPTION, len(line))
        self.assertTrue(text.startswith('\n\n## Skills'))
        self.assertIn('- **triage**: Triage', text)
        self.assertIn(skills.TOOL_NAME, text)


class InvokeTestCase(unittest.IsolatedAsyncioTestCase):
    async def _invoke(
        self,
        prompt: models.Prompt,
        version: models.PromptVersion,
        slug: str = 't',
    ) -> str:
        fetch_prompt = mock.AsyncMock(return_value=(prompt, 3))
        fetch_version = mock.AsyncMock(return_value=version)
        with (
            mock.patch.object(resolve, 'fetch_prompt', fetch_prompt),
            mock.patch.object(resolve, 'fetch_version', fetch_version),
        ):
            text = await skills.invoke(mock.Mock(), slug, 'repo x')
        fetch_prompt.assert_awaited_once_with(mock.ANY, skills.NAMESPACE, slug)
        fetch_version.assert_awaited_once_with(mock.ANY, prompt, 2)
        return text

    async def test_arguments_only_when_declared(self) -> None:
        prompt = _prompt()
        declared = _version(prompt, 'Go {{ arguments }}', ('arguments',))
        self.assertEqual('Go repo x', await self._invoke(prompt, declared))
        plain = _version(prompt, 'Go')
        self.assertEqual('Go', await self._invoke(prompt, plain))

    async def test_selector_in_slug_is_not_parsed(self) -> None:
        prompt = _prompt()
        await self._invoke(prompt, _version(prompt, 'x'), slug='t@draft')

    async def test_default_label_when_no_stable(self) -> None:
        prompt = _prompt(
            labels=[_label('prod', 2)],
            default_label='prod',
        )
        self.assertEqual(
            'x', await self._invoke(prompt, _version(prompt, 'x'))
        )

    async def test_archived_decision_or_unlabeled_is_not_found(self) -> None:
        for prompt in (
            _prompt(archived_at='2026-01-01T00:00Z'),
            _prompt(kind='decision'),
            _prompt(labels=[]),
        ):
            with (
                self.subTest(prompt=prompt),
                mock.patch.object(
                    resolve,
                    'fetch_prompt',
                    mock.AsyncMock(return_value=(prompt, 1)),
                ),
                self.assertRaises(resolve.PromptNotFound),
            ):
                await skills.invoke(mock.Mock(), 't')


class ExecuteTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_execute(self) -> None:
        self.assertTrue((await skills.execute(None, {'name': 't'}))[1])
        for error in (
            resolve.PromptNotFound('Skill t not found'),
            rendering.RenderError('bad'),
        ):
            with (
                self.subTest(error=error),
                mock.patch.object(
                    skills, 'invoke', mock.AsyncMock(side_effect=error)
                ),
            ):
                text, is_error = await skills.execute(
                    mock.Mock(), {'name': 't'}
                )
                self.assertTrue(is_error)
                self.assertIn(str(error), text)
        invoke = mock.AsyncMock(return_value='Go')
        db = mock.Mock()
        with mock.patch.object(skills, 'invoke', invoke):
            result = await skills.execute(db, {'name': 't', 'arguments': 'a'})
        self.assertEqual(('Go', False), result)
        invoke.assert_awaited_once_with(db, 't', 'a')

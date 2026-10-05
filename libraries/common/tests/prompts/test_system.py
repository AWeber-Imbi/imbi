"""Tests for the consumer system-prompt loader and its defaults."""

import re
import typing
import unittest
from unittest import mock

from imbi.common import models
from imbi.common.prompts import rendering, resolve, system

#: Values that would break a naive renderer: braces, Jinja delimiters,
#: Slack link syntax, and newlines.
TRICKY = {
    'display_name': 'Ada {Lovelace} {{ not_a_var }}',
    'email': 'ada@example.com',
    'admin_flag': '  [Admin]',
    'perms_section': 'User permissions: a:b, {% raw %}.',
    'tools_section': 'Available tools: x, y.\nUse them.',
    'links_section': 'The Imbi UI is at <https://imbi/x|x>:\n\n/a\n/b\n',
}


def _str_format_template(default: system.DefaultPrompt) -> str:
    """Undo the ``{{ x }}`` conversion, giving the pre-CMS template."""
    return re.sub(r'\{\{ ([a-z_]+) \}\}', r'{\1}', default.text())


class DefaultTemplateTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_render_matches_str_format_byte_for_byte(self) -> None:
        for default in system.DEFAULT_PROMPTS:
            variables = {name: TRICKY[name] for name in default.variables}
            with self.subTest(prompt=default.ref):
                expected = _str_format_template(default).format(**variables)
                missing = mock.AsyncMock(
                    side_effect=resolve.PromptNotFound('not seeded')
                )
                with mock.patch.object(resolve, 'resolve', missing):
                    result = await system.load_system_prompt(
                        mock.AsyncMock(), default.ref, variables, default
                    )
                self.assertEqual(result.source, 'fallback')
                self.assertEqual(result.text, expected)

    def test_templates_declare_exactly_their_variables(self) -> None:
        for default in system.DEFAULT_PROMPTS:
            with self.subTest(prompt=default.ref):
                found = set(re.findall(r'\{\{ ([a-z_]+) \}\}', default.text()))
                self.assertEqual(found, set(default.variables))
                rendering.check_syntax({'system': default.text()})


def _version(
    system_text: str = 'Hi {{ display_name }}',
    *,
    model: str | None = None,
    model_id: str | None = None,
    params: dict[str, typing.Any] | None = None,
    schema: tuple[str, ...] = ('display_name',),
) -> tuple[models.Prompt, models.PromptVersion, str]:
    prompt = models.Prompt(name='A', slug='system', namespace='imbi-assistant')
    version = models.PromptVersion(
        prompt=prompt,
        prompt_id=prompt.id,
        n=3,
        system=system_text,
        model=model,
        model_id=model_id,
        params=models.PromptParams(**(params or {})),
        variable_schema={
            name: models.PromptVariable(type='str', required=True)
            for name in schema
        },
        content_sha256='x',
        created_by='t',
    )
    return prompt, version, 'stable'


VARIABLES = {name: f'<{name}>' for name in system.ASSISTANT.variables}
REF = 'imbi-assistant/system@stable'


class LoadSystemPromptTestCase(unittest.IsolatedAsyncioTestCase):
    async def load(self, **kwargs: typing.Any) -> system.SystemPrompt:
        return await system.load_system_prompt(
            mock.AsyncMock(), REF, VARIABLES, system.ASSISTANT, **kwargs
        )

    def patch_resolve(self, result: object) -> mock._patch[mock.AsyncMock]:
        kwargs: dict[str, typing.Any] = (
            {'side_effect': result}
            if isinstance(result, BaseException)
            else {'return_value': result}
        )
        return mock.patch.object(resolve, 'resolve', mock.AsyncMock(**kwargs))

    def patch_model(self, info: resolve.ModelInfo | None) -> typing.Any:
        return mock.patch.object(
            resolve, 'model_info', mock.AsyncMock(return_value=info)
        )

    async def test_cms_version_is_used_with_its_params(self) -> None:
        found = _version(params={'max_tokens': 2048, 'temperature': 0.2})
        with self.patch_resolve(found):
            result = await self.load()
        self.assertEqual(result.source, 'cms')
        self.assertEqual(result.text, 'Hi <display_name>')
        self.assertEqual(result.ref, 'imbi-assistant/system@3')
        self.assertEqual(result.max_tokens, 2048)
        self.assertEqual(result.temperature, 0.2)
        self.assertIsNone(result.model_id)

    async def test_only_declared_variables_are_passed(self) -> None:
        # The version declares one variable; the consumer passes six.
        with self.patch_resolve(_version()):
            result = await self.load()
        self.assertEqual(result.source, 'cms')

    async def test_missing_prompt_falls_back(self) -> None:
        with self.patch_resolve(resolve.PromptNotFound('nope')):
            result = await self.load()
        self.assertEqual(result.source, 'fallback')
        self.assertIn('<display_name>', result.text)

    async def test_graph_error_falls_back(self) -> None:
        with self.patch_resolve(RuntimeError('db down')):
            result = await self.load()
        self.assertEqual(result.source, 'fallback')

    async def test_render_error_falls_back(self) -> None:
        broken = _version('{{ undefined_name }}')
        with self.patch_resolve(broken):
            result = await self.load()
        self.assertEqual(result.source, 'fallback')

    async def test_anthropic_model_is_used(self) -> None:
        found = _version(model='default-chat', model_id='claude-opus-5-5')
        info = resolve.ModelInfo('claude-opus-5-5', True, 'anthropic')
        with self.patch_resolve(found), self.patch_model(info):
            result = await self.load()
        self.assertEqual(result.model_id, 'claude-opus-5-5')

    async def test_other_driver_keeps_the_configured_model(self) -> None:
        found = _version(model='gpt', model_id='gpt-5')
        info = resolve.ModelInfo('gpt-5', True, 'openai')
        with self.patch_resolve(found), self.patch_model(info):
            with self.assertLogs(system.LOGGER, 'WARNING'):
                result = await self.load()
        self.assertEqual(result.source, 'cms')
        self.assertIsNone(result.model_id)

    async def test_disabled_model_keeps_the_configured_model(self) -> None:
        found = _version(model='old', model_id='claude-old')
        info = resolve.ModelInfo('claude-old', False, 'anthropic')
        with self.patch_resolve(found), self.patch_model(info):
            result = await self.load()
        self.assertIsNone(result.model_id)

    async def test_override_wins(self) -> None:
        with self.patch_resolve(_version()) as found:
            result = await self.load(override='Custom {{ email }}')
        self.assertEqual(result.source, 'override')
        self.assertEqual(result.text, 'Custom <email>')
        found.assert_not_awaited()

    async def test_broken_override_falls_back(self) -> None:
        with self.assertLogs(system.LOGGER, 'ERROR'):
            result = await self.load(override='Old {email} {{ oops')
        self.assertEqual(result.source, 'fallback')


class ResolveTestCase(unittest.IsolatedAsyncioTestCase):
    def test_parse_ref(self) -> None:
        self.assertEqual(
            resolve.parse_ref('imbi-assistant/system@stable'),
            ('imbi-assistant', 'system', 'stable'),
        )
        self.assertEqual(resolve.parse_ref('a/b'), ('a', 'b', None))
        with self.assertRaises(resolve.InvalidRef):
            resolve.parse_ref('no-slash')

    async def test_unknown_label_uses_the_default_label(self) -> None:
        prompt, version, _ = _version()
        prompt.labels = [
            models.PromptLabel(
                name='stable',
                version=3,
                updated_by='t',
                updated_at=prompt.created_at,
            )
        ]
        db = mock.AsyncMock()
        db.execute.side_effect = [
            [{'p': prompt.model_dump(mode='json'), 'latest': 3}],
            [{'v': version.model_dump(mode='json', exclude={'prompt'})}],
        ]
        with mock.patch.object(
            resolve.graph, 'parse_agtype', side_effect=lambda value: value
        ):
            _p, found, label = await resolve.resolve(
                db, 'imbi-assistant/system@nope'
            )
        self.assertEqual((label, found.n), ('stable', 3))

    async def test_missing_prompt(self) -> None:
        db = mock.AsyncMock()
        db.execute.return_value = []
        with self.assertRaises(resolve.PromptNotFound):
            await resolve.resolve(db, 'a/b')

"""Tests for the consumer system-prompt loader and its defaults."""

import re
import typing
import unittest
from unittest import mock

from imbi.common import models
from imbi.common.llm import resolve as llm_resolve
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
    """Undo the ``{{ x }}`` conversion, giving the pre-CMS template.

    Literal braces (such as ``{org_slug}`` in a URL pattern) are escaped
    first, because ``str.format`` reads a single brace as a field.
    """
    text = default.text().replace('{', '{{').replace('}', '}}')
    return re.sub(r'\{\{\{\{ ([a-z_]+) \}\}\}\}', r'{\1}', text)


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


def _model(
    slug: str, model_id: str, driver: str = 'anthropic'
) -> llm_resolve.ResolvedModel:
    org = models.Organization(id='org-1', name='O', slug='o')
    provider = models.AIProvider(
        name='P', slug='p', driver=driver, organization=org
    )
    return llm_resolve.ResolvedModel(
        source='explicit',
        model=models.AIModel(
            name=slug,
            slug=slug,
            model_id=model_id,
            provider=provider,
            organization=org,
        ),
    )


VARIABLES = {name: f'<{name}>' for name in system.ASSISTANT.variables}
REF = 'imbi-assistant/system@stable'


class LoadSystemPromptTestCase(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        patcher = mock.patch.object(
            resolve, 'member_org_ids', mock.AsyncMock(return_value=['org-1'])
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    async def load(self, **kwargs: typing.Any) -> system.SystemPrompt:
        kwargs.setdefault('email', 'dev@example.com')
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

    def patch_model(self, result: object) -> typing.Any:
        kwargs: dict[str, typing.Any] = (
            {'side_effect': result}
            if isinstance(result, BaseException)
            else {'return_value': result}
        )
        return mock.patch.object(
            llm_resolve, 'resolve_model', mock.AsyncMock(**kwargs)
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
        resolved = _model('default-chat', 'claude-opus-5-5')
        with (
            self.patch_resolve(found),
            self.patch_model(resolved) as resolver,
        ):
            result = await self.load(email='dev@example.com')
        self.assertEqual(result.model_id, 'claude-opus-5-5')
        # The provider comes with the model, for its credential.
        assert resolved.model is not None
        self.assertIs(result.provider, resolved.model.provider)
        resolver.assert_awaited_once_with(
            mock.ANY, ['org-1'], model='default-chat', email='dev@example.com'
        )

    async def test_no_user_has_no_catalog_model(self) -> None:
        found = _version(model='default-chat', model_id='claude-opus-5-5')
        with self.patch_resolve(found), self.patch_model(None) as resolver:
            result = await self.load(email=None)
        self.assertIsNone(result.model_id)
        resolver.assert_not_awaited()

    async def test_other_driver_is_an_error(self) -> None:
        found = _version(model='gpt', model_id='gpt-5')
        with (
            self.patch_resolve(found),
            self.patch_model(_model('gpt', 'gpt-5', 'openai')),
            self.assertRaises(llm_resolve.ModelUnusable) as raised,
        ):
            await self.load()
        self.assertEqual(raised.exception.reason, 'unsupported_driver')

    async def test_unusable_model_is_an_error(self) -> None:
        # No other model is used in its place (ADR 0018).
        found = _version(model='old', model_id='claude-old')
        for reason in typing.get_args(llm_resolve.Reason):
            error = llm_resolve.ModelUnusable(reason, 'old', 'no')
            with (
                self.subTest(reason=reason),
                self.patch_resolve(found),
                self.patch_model(error),
                self.assertRaises(llm_resolve.ModelUnusable),
            ):
                await self.load(email='dev@example.com')
            with (
                self.subTest(reason=reason, loader='load_model'),
                self.patch_resolve(found),
                self.patch_model(error),
                self.assertRaises(llm_resolve.ModelUnusable),
            ):
                await system.load_model(
                    mock.AsyncMock(), REF, 'dev@example.com'
                )

    async def test_stale_model_id_is_checked(self) -> None:
        # A catalog edit moved the slug to a new id; the version keeps
        # the old one, and the old one is what is sent.
        found = _version(model='opus', model_id='claude-opus-old')
        resolved = _model('opus', 'claude-opus-5-5')
        for allowed in (False, True):
            with (
                self.subTest(allowed=allowed),
                self.patch_resolve(found),
                self.patch_model(resolved),
                mock.patch.object(
                    resolve,
                    'member_may_use_model_id',
                    mock.AsyncMock(return_value=allowed),
                ) as check,
            ):
                if allowed:
                    result = await self.load(email='dev@example.com')
                    self.assertEqual(result.model_id, 'claude-opus-old')
                else:
                    with self.assertRaises(llm_resolve.ModelUnusable):
                        await self.load(email='dev@example.com')
                check.assert_awaited_once_with(
                    mock.ANY,
                    'claude-opus-old',
                    'dev@example.com',
                    org_ids=['org-1'],
                )

    async def test_graph_error_in_the_model_check_falls_back(self) -> None:
        found = _version(model='opus', model_id='claude-opus-5-5')
        with (
            self.patch_resolve(found),
            self.patch_model(RuntimeError('db down')),
            self.assertLogs(system.LOGGER, 'WARNING'),
        ):
            result = await self.load(email='dev@example.com')
        self.assertEqual(result.source, 'fallback')
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


class DefaultModelIdTestCase(unittest.IsolatedAsyncioTestCase):
    async def default(self, result: object) -> str | None:
        kwargs: dict[str, typing.Any] = (
            {'side_effect': result}
            if isinstance(result, BaseException)
            else {'return_value': result}
        )
        with (
            mock.patch.object(
                resolve,
                'member_org_ids',
                mock.AsyncMock(return_value=['org-1']),
            ),
            mock.patch.object(
                llm_resolve, 'resolve_model', mock.AsyncMock(**kwargs)
            ) as resolver,
        ):
            found = await system.default_model(
                mock.AsyncMock(), 'dev@example.com'
            )
        resolver.assert_awaited_once_with(
            mock.ANY, ['org-1'], email='dev@example.com'
        )
        return found

    async def test_organization_default(self) -> None:
        resolved = _model('chat', 'claude-chat')
        found = await self.default(resolved)
        assert found is not None and resolved.model is not None
        self.assertEqual(found.model_id, 'claude-chat')
        self.assertIs(found.provider, resolved.model.provider)

    async def test_one_named_organization(self) -> None:
        # The Slack bot names the organization of its workspace, so only
        # that catalog is read.
        db = mock.AsyncMock()
        db.execute.return_value = [{'id': 'org-2'}]
        with (
            mock.patch.object(
                resolve.graph, 'parse_agtype', side_effect=lambda v: v
            ),
            mock.patch.object(
                llm_resolve,
                'resolve_model',
                mock.AsyncMock(return_value=llm_resolve.ResolvedModel('env')),
            ) as resolver,
        ):
            await system.default_model(db, 'dev@example.com', org_slug='acme')
        db.execute.assert_awaited_once_with(
            system.MEMBER_ORG_QUERY,
            {'email': 'dev@example.com', 'org': 'acme'},
            ['id'],
        )
        resolver.assert_awaited_once_with(
            mock.ANY, ['org-2'], email='dev@example.com'
        )

    async def test_no_default_is_none(self) -> None:
        resolved = llm_resolve.ResolvedModel(source='env')
        self.assertIsNone(await self.default(resolved))

    async def test_other_driver_is_an_error(self) -> None:
        with self.assertRaises(llm_resolve.ModelUnusable) as raised:
            await self.default(_model('gpt', 'gpt-5', 'openai'))
        self.assertEqual(raised.exception.reason, 'unsupported_driver')

    async def test_unusable_default_is_an_error(self) -> None:
        error = llm_resolve.ModelUnusable('disabled', 'chat', 'no')
        with self.assertRaises(llm_resolve.ModelUnusable):
            await self.default(error)


class UnlabelledPromptTestCase(unittest.IsolatedAsyncioTestCase):
    async def test_prompt_without_labels_uses_the_fallback(self) -> None:
        # A prompt created without promote authority has no labels, so
        # it must not reach consumers until someone promotes a version.
        prompt, _version_node, _ = _version()
        prompt.labels = []
        db = mock.AsyncMock()
        db.execute.return_value = [
            {'p': prompt.model_dump(mode='json'), 'latest': 1}
        ]
        with mock.patch.object(
            resolve.graph, 'parse_agtype', side_effect=lambda value: value
        ):
            result = await system.load_system_prompt(
                db, REF, VARIABLES, system.ASSISTANT
            )
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

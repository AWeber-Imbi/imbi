"""Tests for prompt CMS template rendering."""

import typing
import unittest

from imbi.api.prompts import rendering
from imbi.common import models


def version(
    system: str, **schema: models.PromptVariable
) -> models.PromptVersion:
    prompt = models.Prompt(
        organization=models.Organization(name='', slug='acme'),
        namespace='demo',
        name='Demo',
        slug='core',
    )
    return models.PromptVersion(
        prompt=prompt,
        prompt_id=prompt.id,
        n=1,
        system=system,
        variable_schema=schema,
        content_sha256='x',
        created_by='test',
    )


class RenderTestCase(unittest.IsolatedAsyncioTestCase):
    async def render(
        self,
        system: str,
        variables: dict[str, typing.Any] | None = None,
        providers: dict[str, rendering.Provider] | None = None,
        **schema: models.PromptVariable,
    ) -> str:
        result = await rendering.render(
            version(system, **schema), variables or {}, providers or {}
        )
        return result.system

    async def test_renders_variables(self) -> None:
        text = await self.render(
            'Hi {{ name }}',
            {'name': 'Ada'},
            name=models.PromptVariable(type='str'),
        )
        self.assertEqual(text, 'Hi Ada')

    async def test_undefined_is_an_error(self) -> None:
        with self.assertRaisesRegex(rendering.RenderError, 'Undefined'):
            await self.render('Hi {{ name }}')

    async def test_blocks_python_internals(self) -> None:
        with self.assertRaises(rendering.RenderError):
            await self.render("{{ ''.__class__.__mro__ }}")

    async def test_caps_range(self) -> None:
        with self.assertRaisesRegex(rendering.RenderError, 'range'):
            await self.render('{% for i in range(5000) %}x{% endfor %}')

    async def test_caps_output(self) -> None:
        with self.assertRaisesRegex(rendering.RenderError, 'limit'):
            await self.render(
                "{% for i in range(1000) %}{{ 'x' * 1000 }}{% endfor %}"
            )

    async def test_wrong_type_is_an_error(self) -> None:
        with self.assertRaisesRegex(rendering.RenderError, 'type int'):
            await self.render(
                '{{ n }}', {'n': True}, n=models.PromptVariable(type='int')
            )

    async def test_provider_is_awaited_and_memoized(self) -> None:
        calls: list[object] = []

        async def project(project_id: object) -> object:
            calls.append(project_id)
            return {'name': 'Billing', 'team': {'slug': 'payments'}}

        text = await self.render(
            '{{ project(1).name }}/{{ project(1).team.slug }}',
            providers={'project': project},
        )
        self.assertEqual(text, 'Billing/payments')
        self.assertEqual(calls, [1])


class CheckTestCase(unittest.TestCase):
    def test_syntax_error_names_the_field(self) -> None:
        with self.assertRaisesRegex(rendering.RenderError, 'messages\\[0\\]'):
            rendering.check_syntax({'messages[0]': '{% if %}'})

    def test_variable_names(self) -> None:
        with self.assertRaises(rendering.RenderError):
            rendering.check_variable_schema(
                {'bad-name': models.PromptVariable(type='str')}, set()
            )

"""Tests for prompt CMS template rendering."""

import time
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

    async def test_caps_repetition_before_it_runs(self) -> None:
        with self.assertRaisesRegex(rendering.RenderError, 'limit'):
            await self.render("{{ 'x' * 1000000000 }}")

    async def test_caps_concatenation(self) -> None:
        with self.assertRaisesRegex(rendering.RenderError, 'limit'):
            await self.render("{% set s = 'x' * 200000 %}{{ s + s }}")

    async def test_caps_exponent(self) -> None:
        with self.assertRaisesRegex(rendering.RenderError, 'too large'):
            await self.render('{{ 10 ** 100000000 }}')

    async def test_blocks_padding(self) -> None:
        for source in (
            "{{ 'x'.center(1000000000) }}",
            "{{ '%1000000000s' % 'x' }}",
            "{{ '{:>1000000000}'.format('x') }}",
            "{{ 'x'|indent(1000000000) }}",
            "{{ range(1000)|join('x' * 200000) }}",
            '{{ lipsum(1000000) }}',
        ):
            with self.subTest(source=source):
                with self.assertRaises(rendering.RenderError):
                    await self.render(source)

    async def test_ordinary_filters_still_work(self) -> None:
        text = await self.render(
            "{{ range(3)|join(', ') }}|{{ range(3)|map('string')|join }}"
            "|{{ 'a\\nb'|indent(2) }}"
        )
        self.assertEqual(text, '0, 1, 2|012|a\n  b')

    async def test_blocks_size_bypasses(self) -> None:
        for source in (
            # Nested list repetition: short outer list, huge str().
            "{{ [['x' * 200000]] * 1000 }}",
            "{{ ([['x' * 200000]] * 1000)|string }}",
            # Concatenation with ~ in one expression.
            "{% set s = 'x' * 200000 %}{{ s ~ s ~ s }}",
            # bytes have no checks, so encode must not be reachable.
            "{{ 'x'.encode() * 1000000000 }}",
            # replace with an empty pattern multiplies the input.
            "{{ ('x' * 1000)|replace('', 'y' * 1000) }}",
            # Integer growth by bit length, not exponent.
            '{{ ((2 ** 64) ** 64) ** 64 }}',
            '{{ (10 ** 64) * (10 ** 64) * (10 ** 2000) }}',
            # Filters with caller-sized output are not available.
            "{{ range(10)|batch(1000000000, 'x')|list }}",
            "{{ range(10)|slice(1000000000, 'x')|list }}",
            "{{ 'x'|wordwrap(1, wrapstring='y' * 1000000) }}",
        ):
            with self.subTest(source=source):
                with self.assertRaises(rendering.RenderError):
                    await self.render(source)

    async def test_tojson_rejects_indent(self) -> None:
        for source in (
            '{{ range(1000)|list|tojson(indent=100000000) }}',
            "{{ [1, 2]|tojson('x' * 200000) }}",
        ):
            with self.subTest(source=source):
                with self.assertRaisesRegex(rendering.RenderError, 'indent'):
                    await self.render(source)

    async def test_tojson_still_works(self) -> None:
        text = await self.render("{{ {'a': [1, 2]}|tojson }}")
        self.assertEqual(text, '{"a": [1, 2]}')

    async def test_caps_work_in_silent_loops(self) -> None:
        for source in (
            # Nested loops over a large split, with no output.
            "{% set xs = ('x' * 200000).split('x') %}"
            '{% for a in xs %}{% for b in xs %}{% if b %}{% endif %}'
            '{% endfor %}{% endfor %}',
            # Expensive work in each iteration of one loop.
            "{% set s = 'x' * 200000 %}"
            '{% for a in s.split("x") %}{% if s.split("x") %}{% endif %}'
            '{% endfor %}',
            "{% set xs = ('x' * 200000).split('x') %}"
            '{% for a in xs %}{% if xs|sort %}{% endif %}{% endfor %}',
        ):
            with self.subTest(source=source[:60]):
                with self.assertRaisesRegex(rendering.RenderError, 'work'):
                    await self.render(source)

    async def test_caps_operand_sized_work(self) -> None:
        big = "{% set xs = ('x' * 200000).split('x') %}"
        loop = '{% for a in range(1000) %}{% for b in range(1000) %}'
        end = '{% endfor %}{% endfor %}'
        for source in (
            # ``in`` against a large container inside nested loops.
            big + loop + "{% if 'y' in xs %}{% endif %}" + end,
            # A test with a large operand, called once per item.
            big + "{% for a in range(1000) %}{{ range(1000)|select('in', xs)"
            '|list|length }}{% endfor %}',
            # Slicing copies a large list in every iteration.
            big + loop + '{% if xs[0:200000] %}{% endif %}' + end,
            # Sorting cost grows faster than the input.
            big + '{% for a in range(1000) %}{% if xs|unique|list %}'
            '{% endif %}{% endfor %}',
        ):
            with self.subTest(source=source[:70]):
                started = time.monotonic()
                with self.assertRaisesRegex(rendering.RenderError, 'work'):
                    await self.render(source)
                self.assertLess(time.monotonic() - started, 2.0)

    async def test_blocks_container_methods(self) -> None:
        for source in (
            '{{ [3, 1, 2].index(1) }}',
            '{{ (1, 2).count(1) }}',
            '{{ {"a": 1}.copy() }}',
        ):
            with self.subTest(source=source):
                with self.assertRaises(rendering.RenderError):
                    await self.render(source)

    async def test_ordinary_compares_tests_and_methods(self) -> None:
        text = await self.render(
            "{% if 'a' in items %}yes{% endif %}"
            '|{{ people|selectattr("on")|map(attribute="n")|join(",") }}'
            "|{{ project.get('name') }}|{% if 1 < 2 < 3 %}ok{% endif %}"
            '|{{ items[0:2]|join }}|{{ items|sort|join }}',
            {
                'items': ['c', 'a', 'b'],
                'people': [{'n': 'x', 'on': True}, {'n': 'y', 'on': False}],
                'project': {'name': 'billing'},
            },
            items=models.PromptVariable(type='list'),
            people=models.PromptVariable(type='list'),
            project=models.PromptVariable(type='object'),
        )
        self.assertEqual(text, 'yes|x|billing|ok|ca|abc')

    async def test_ordinary_loops_fit_the_budget(self) -> None:
        text = await self.render(
            '{% for i in range(100) %}{% for j in range(100) %}'
            '{% endfor %}{% endfor %}'
            '{% for item in items %}{{ item.name|upper }} {% endfor %}',
            {'items': [{'name': f'n{i}'} for i in range(500)]},
            items=models.PromptVariable(type='list'),
        )
        self.assertTrue(text.startswith('N0 N1 '))

    async def test_namespace_is_not_available(self) -> None:
        with self.assertRaises(rendering.RenderError):
            await self.render('{% set ns = namespace(s=1) %}{{ ns.s }}')

    async def test_streamed_output_is_capped(self) -> None:
        with self.assertRaisesRegex(rendering.RenderError, 'limit'):
            await self.render(
                '{% for i in range(1000) %}{% for j in range(1000) %}'
                'x{% endfor %}{% endfor %}'
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

    def test_rejects_macros(self) -> None:
        with self.assertRaisesRegex(rendering.RenderError, 'Macros'):
            rendering.check_syntax(
                {'system': '{% macro m() %}x{% endmacro %}{{ m() }}'}
            )

    def test_rejects_deep_loops(self) -> None:
        source = (
            '{% for a in range(2) %}{% for b in range(2) %}'
            '{% for c in range(2) %}x{% endfor %}{% endfor %}{% endfor %}'
        )
        with self.assertRaisesRegex(rendering.RenderError, 'nest'):
            rendering.check_syntax({'system': source})

    def test_rejects_recursive_loops(self) -> None:
        source = '{% for x in [1] recursive %}{{ loop([x]) }}{% endfor %}'
        with self.assertRaisesRegex(rendering.RenderError, 'Recursive'):
            rendering.check_syntax({'system': source})

    def test_variable_names(self) -> None:
        with self.assertRaises(rendering.RenderError):
            rendering.check_variable_schema(
                {'bad-name': models.PromptVariable(type='str')}, set()
            )

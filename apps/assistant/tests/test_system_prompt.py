"""Tests for assistant system_prompt module."""

import os
import unittest
from unittest import mock

from imbi.assistant import auth, settings, system_prompt
from imbi.common.prompts import resolve


def _make_auth_context(
    is_admin: bool = False,
    perms: set[str] | None = None,
) -> auth.AuthContext:
    """Create a test AuthContext."""
    user = auth.User(
        email='test@example.com',
        display_name='Test User',
        is_admin=is_admin,
    )
    return auth.AuthContext(
        user=user,
        auth_method='jwt',
        permissions=perms or set(),
    )


def _no_cms() -> mock._patch[mock.AsyncMock]:
    """Make the CMS lookup report that the prompt is not seeded."""
    return mock.patch.object(
        resolve,
        'resolve',
        mock.AsyncMock(side_effect=resolve.PromptNotFound('not seeded')),
    )


class BuildSystemPromptTestCase(unittest.IsolatedAsyncioTestCase):
    """Test cases for build_system_prompt."""

    def setUp(self) -> None:
        settings._assistant_settings = None

    def tearDown(self) -> None:
        settings._assistant_settings = None

    async def build(self, auth_ctx: auth.AuthContext, tools: list[str]) -> str:
        with _no_cms():
            result = await system_prompt.build_system_prompt(
                mock.AsyncMock(), auth_ctx, tools
            )
        return result.text

    @mock.patch.dict(os.environ, {}, clear=True)
    async def test_packaged_prompt_without_cms(self) -> None:
        with _no_cms():
            result = await system_prompt.build_system_prompt(
                mock.AsyncMock(), _make_auth_context(), []
            )
        self.assertEqual(result.source, 'fallback')
        self.assertIn('Test User', result.text)
        self.assertIn('NO tools available', result.text)

    @mock.patch.dict(os.environ, {}, clear=True)
    async def test_reads_the_configured_ref(self) -> None:
        found = mock.AsyncMock(side_effect=resolve.PromptNotFound('x'))
        with mock.patch.object(resolve, 'resolve', found):
            await system_prompt.build_system_prompt(
                mock.AsyncMock(), _make_auth_context(), []
            )
        self.assertEqual(
            found.await_args.args[1], 'imbi-assistant/system@stable'
        )

    @mock.patch.dict(
        os.environ,
        {
            'IMBI_ASSISTANT_SYSTEM_PROMPT': (
                'Hello {{ display_name }} ({{ email }})'
                '{{ admin_flag }}. '
                '{{ perms_section }} {{ tools_section }}'
            ),
        },
        clear=True,
    )
    async def test_build_with_tools_and_perms(self) -> None:
        auth_ctx = _make_auth_context(
            perms={'project:read', 'team:read'},
        )
        result = await self.build(auth_ctx, ['list_projects', 'list_teams'])
        self.assertIn('Test User', result)
        self.assertIn('test@example.com', result)
        self.assertIn('list_projects', result)
        self.assertIn('project:read', result)

    @mock.patch.dict(
        os.environ,
        {
            'IMBI_ASSISTANT_SYSTEM_PROMPT': (
                'Hello {{ display_name }}{{ admin_flag }}. '
                '{{ perms_section }} {{ tools_section }}'
            ),
        },
        clear=True,
    )
    async def test_build_admin_flag(self) -> None:
        result = await self.build(_make_auth_context(is_admin=True), [])
        self.assertIn('[Admin]', result)

    @mock.patch.dict(
        os.environ,
        {
            'IMBI_ASSISTANT_SYSTEM_PROMPT': (
                'Hello {{ display_name }}{{ admin_flag }}. '
                '{{ perms_section }} {{ tools_section }}'
            ),
        },
        clear=True,
    )
    async def test_build_no_tools_no_perms(self) -> None:
        result = await self.build(_make_auth_context(), [])
        self.assertIn('Test User', result)
        self.assertNotIn('[Admin]', result)

    @mock.patch.dict(
        os.environ,
        {
            'IMBI_UI_URL': 'https://imbi.example.com',
            'IMBI_ASSISTANT_SYSTEM_PROMPT': '{{ links_section }}',
        },
        clear=True,
    )
    async def test_build_injects_base_url(self) -> None:
        result = await self.build(_make_auth_context(), [])
        self.assertIn('https://imbi.example.com', result)

    @mock.patch.dict(
        os.environ,
        {'IMBI_ASSISTANT_SYSTEM_PROMPT': 'Old style {display_name} {{'},
        clear=True,
    )
    async def test_broken_override_uses_the_packaged_prompt(self) -> None:
        result = await self.build(_make_auth_context(), [])
        self.assertIn('Test User', result)
        self.assertNotIn('Old style', result)

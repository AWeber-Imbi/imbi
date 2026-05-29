"""Tests for assistant system_prompt module."""

import os
import unittest
from unittest import mock

from imbi_assistant import auth, settings, system_prompt


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


class LoadTemplateTestCase(unittest.TestCase):
    """Test cases for _load_template."""

    def setUp(self) -> None:
        system_prompt._prompt_template = None
        settings._assistant_settings = None

    def tearDown(self) -> None:
        system_prompt._prompt_template = None
        settings._assistant_settings = None

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_load_from_file(self) -> None:
        template = system_prompt._load_template()
        self.assertIsInstance(template, str)
        self.assertTrue(len(template) > 0)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_load_caches_template(self) -> None:
        t1 = system_prompt._load_template()
        t2 = system_prompt._load_template()
        self.assertIs(t1, t2)

    @mock.patch.dict(
        os.environ,
        {
            'IMBI_ASSISTANT_SYSTEM_PROMPT': ('Custom prompt {display_name}'),
        },
        clear=True,
    )
    def test_load_from_env(self) -> None:
        template = system_prompt._load_template()
        self.assertEqual(template, 'Custom prompt {display_name}')


class BuildSystemPromptTestCase(unittest.TestCase):
    """Test cases for build_system_prompt."""

    def setUp(self) -> None:
        system_prompt._prompt_template = None
        settings._assistant_settings = None

    def tearDown(self) -> None:
        system_prompt._prompt_template = None
        settings._assistant_settings = None

    @mock.patch.dict(
        os.environ,
        {
            'IMBI_ASSISTANT_SYSTEM_PROMPT': (
                'Hello {display_name} ({email})'
                '{admin_flag}. '
                '{perms_section} {tools_section}'
            ),
        },
        clear=True,
    )
    def test_build_with_tools_and_perms(self) -> None:
        auth_ctx = _make_auth_context(
            perms={'project:read', 'team:read'},
        )
        result = system_prompt.build_system_prompt(
            auth_ctx, ['list_projects', 'list_teams']
        )
        self.assertIn('Test User', result)
        self.assertIn('test@example.com', result)
        self.assertIn('list_projects', result)
        self.assertIn('project:read', result)

    @mock.patch.dict(
        os.environ,
        {
            'IMBI_ASSISTANT_SYSTEM_PROMPT': (
                'Hello {display_name}{admin_flag}. '
                '{perms_section} {tools_section}'
            ),
        },
        clear=True,
    )
    def test_build_admin_flag(self) -> None:
        auth_ctx = _make_auth_context(is_admin=True)
        result = system_prompt.build_system_prompt(auth_ctx, [])
        self.assertIn('[Admin]', result)

    @mock.patch.dict(
        os.environ,
        {
            'IMBI_ASSISTANT_SYSTEM_PROMPT': (
                'Hello {display_name}{admin_flag}. '
                '{perms_section} {tools_section}'
            ),
        },
        clear=True,
    )
    def test_build_no_tools_no_perms(self) -> None:
        auth_ctx = _make_auth_context()
        result = system_prompt.build_system_prompt(auth_ctx, [])
        self.assertIn('Test User', result)
        self.assertNotIn('[Admin]', result)

    @mock.patch.dict(
        os.environ,
        {
            'IMBI_UI_URL': 'https://imbi.example.com',
            'IMBI_ASSISTANT_SYSTEM_PROMPT': '{links_section}',
        },
        clear=True,
    )
    def test_build_injects_base_url(self) -> None:
        auth_ctx = _make_auth_context()
        result = system_prompt.build_system_prompt(auth_ctx, [])
        self.assertIn('https://imbi.example.com', result)

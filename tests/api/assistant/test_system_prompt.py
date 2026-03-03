"""Tests for assistant system_prompt module."""

import datetime
import os
import unittest
from unittest import mock

from imbi_api import models
from imbi_api.assistant import settings, system_prompt
from imbi_api.auth import permissions


def _make_auth(
    is_admin: bool = False,
    perms: set[str] | None = None,
) -> permissions.AuthContext:
    """Create a test AuthContext."""
    user = models.User(
        email='test@example.com',
        display_name='Test User',
        is_admin=is_admin,
        created_at=datetime.datetime.now(datetime.UTC),
    )
    return permissions.AuthContext(
        user=user,
        auth_method='jwt',
        permissions=perms or set(),
    )


class LoadTemplateTestCase(unittest.TestCase):
    """Test cases for _load_template."""

    def setUp(self) -> None:
        system_prompt._PROMPT_TEMPLATE = None
        settings._assistant_settings = None

    def tearDown(self) -> None:
        system_prompt._PROMPT_TEMPLATE = None
        settings._assistant_settings = None

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_load_from_file(self) -> None:
        """Test loading template from markdown file."""
        template = system_prompt._load_template()
        self.assertIsInstance(template, str)
        self.assertTrue(len(template) > 0)

    @mock.patch.dict(os.environ, {}, clear=True)
    def test_load_caches_template(self) -> None:
        """Test that template is cached after first load."""
        t1 = system_prompt._load_template()
        t2 = system_prompt._load_template()
        self.assertIs(t1, t2)

    @mock.patch.dict(
        os.environ,
        {'IMBI_ASSISTANT_SYSTEM_PROMPT': 'Custom prompt {display_name}'},
        clear=True,
    )
    def test_load_from_env(self) -> None:
        """Test loading template from environment variable."""
        template = system_prompt._load_template()
        self.assertEqual(template, 'Custom prompt {display_name}')


class BuildSystemPromptTestCase(unittest.TestCase):
    """Test cases for build_system_prompt."""

    def setUp(self) -> None:
        system_prompt._PROMPT_TEMPLATE = None
        settings._assistant_settings = None

    def tearDown(self) -> None:
        system_prompt._PROMPT_TEMPLATE = None
        settings._assistant_settings = None

    @mock.patch.dict(
        os.environ,
        {
            'IMBI_ASSISTANT_SYSTEM_PROMPT': (
                'Hello {display_name} ({email}){admin_flag}. '
                '{perms_section} {tools_section}'
            ),
        },
        clear=True,
    )
    def test_build_with_tools_and_perms(self) -> None:
        """Test building prompt with tools and permissions."""
        auth = _make_auth(
            perms={'project:read', 'team:read'},
        )
        result = system_prompt.build_system_prompt(
            auth, ['list_projects', 'list_teams']
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
        """Test admin flag in prompt."""
        auth = _make_auth(is_admin=True)
        result = system_prompt.build_system_prompt(auth, [])
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
        """Test building prompt with no tools or permissions."""
        auth = _make_auth()
        result = system_prompt.build_system_prompt(auth, [])
        self.assertIn('Test User', result)
        # No admin flag
        self.assertNotIn('[Admin]', result)

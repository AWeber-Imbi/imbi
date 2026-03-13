"""Tests for email module exports."""

import unittest

from imbi_api import email
from imbi_api.email.client import EmailClient
from imbi_api.email.dependencies import (
    InjectEmailClient,
    InjectTemplateManager,
)
from imbi_api.email.templates import TemplateManager


class EmailModuleTestCase(unittest.TestCase):
    """Test cases for email module public API."""

    def test_exports_email_client(self) -> None:
        self.assertIs(email.EmailClient, EmailClient)

    def test_exports_template_manager(self) -> None:
        self.assertIs(email.TemplateManager, TemplateManager)

    def test_exports_inject_email_client(self) -> None:
        self.assertIs(
            email.InjectEmailClient,
            InjectEmailClient,
        )

    def test_exports_inject_template_manager(self) -> None:
        self.assertIs(
            email.InjectTemplateManager,
            InjectTemplateManager,
        )

    def test_exports_send_functions(self) -> None:
        self.assertTrue(callable(email.send_welcome_email))
        self.assertTrue(callable(email.send_password_reset))

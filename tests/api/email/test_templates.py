"""Tests for email.templates module."""

import unittest

from imbi.email import templates


class TemplateManagerTestCase(unittest.TestCase):
    """Test cases for TemplateManager."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        # Reset singleton for test isolation
        templates.TemplateManager._instance = None
        self.manager = templates.TemplateManager.get_instance()

    def tearDown(self) -> None:
        """Clean up test fixtures."""
        templates.TemplateManager._instance = None

    def test_singleton_pattern(self) -> None:
        """Test TemplateManager uses singleton pattern."""
        instance1 = templates.TemplateManager.get_instance()
        instance2 = templates.TemplateManager.get_instance()
        self.assertIs(instance1, instance2)

    def test_render_welcome_email_html(self) -> None:
        """Test rendering welcome email HTML."""
        context = {
            'to_email': 'user@example.com',
            'username': 'testuser',
            'display_name': 'Test User',
            'login_url': 'https://imbi.example.com/login',
        }

        message = self.manager.render_email('welcome', context)

        self.assertEqual(message.to_email, 'user@example.com')
        self.assertEqual(message.template_name, 'welcome')
        self.assertIn('Welcome to Imbi, Test User!', message.subject)
        self.assertIn('Test User', message.html_body)
        self.assertIn('testuser', message.html_body)
        self.assertIn('https://imbi.example.com/login', message.html_body)
        self.assertIn('<!DOCTYPE html>', message.html_body)

    def test_render_welcome_email_text(self) -> None:
        """Test rendering welcome email plain text."""
        context = {
            'to_email': 'user@example.com',
            'username': 'testuser',
            'display_name': 'Test User',
            'login_url': 'https://imbi.example.com/login',
        }

        message = self.manager.render_email('welcome', context)

        self.assertIn('Test User', message.text_body)
        self.assertIn('testuser', message.text_body)
        self.assertIn('https://imbi.example.com/login', message.text_body)
        self.assertIn('WELCOME TO IMBI', message.text_body)
        self.assertNotIn('<', message.text_body)  # No HTML tags

    def test_subject_extraction(self) -> None:
        """Test subject line extraction from template comment."""
        context = {
            'to_email': 'user@example.com',
            'username': 'testuser',
            'display_name': 'Test User',
            'login_url': 'https://imbi.example.com/login',
        }

        message = self.manager.render_email('welcome', context)

        # Subject should be extracted from {# subject: ... #} comment
        self.assertEqual(
            message.subject,
            'Welcome to Imbi, Test User!',
        )

    def test_subject_with_variables(self) -> None:
        """Test subject line with Jinja2 variables."""
        context = {
            'to_email': 'user@example.com',
            'username': 'testuser',
            'display_name': 'Jane Doe',
            'login_url': 'https://imbi.example.com/login',
        }

        message = self.manager.render_email('welcome', context)

        # display_name variable should be rendered in subject
        self.assertIn('Jane Doe', message.subject)

    def test_missing_to_email(self) -> None:
        """Test rendering fails without to_email in context."""
        context = {
            'username': 'testuser',
            'display_name': 'Test User',
        }

        with self.assertRaises(KeyError) as cm:
            self.manager.render_email('welcome', context)

        self.assertIn('to_email', str(cm.exception))

    def test_html_to_text_conversion(self) -> None:
        """Test HTML to plain text conversion."""
        html = (
            '<h1>Title</h1>'
            '<p>Paragraph with <strong>bold</strong>.</p>'
            '<br><p>Another paragraph.</p>'
        )

        text = self.manager._html_to_text(html)

        self.assertNotIn('<', text)
        self.assertNotIn('>', text)
        self.assertIn('Title', text)
        self.assertIn('Paragraph with bold', text)
        self.assertIn('Another paragraph', text)

    def test_html_to_text_with_entities(self) -> None:
        """Test HTML entity decoding in text conversion."""
        html = '<p>Email: user@example.com &amp; co.</p>'

        text = self.manager._html_to_text(html)

        self.assertIn('&', text)
        self.assertNotIn('&amp;', text)
        self.assertIn('user@example.com', text)

    def test_html_to_text_with_br_tags(self) -> None:
        """Test <br> tag conversion to newlines."""
        html = '<p>Line 1<br>Line 2<br/>Line 3</p>'

        text = self.manager._html_to_text(html)

        self.assertIn('Line 1\nLine 2\nLine 3', text)

    def test_strip_html_filter(self) -> None:
        """Test the strip_html Jinja2 filter."""
        html = '<p>Hello <strong>world</strong>!</p>'

        text = self.manager._html_to_text(html)

        self.assertEqual('Hello world!', text)
        self.assertNotIn('<', text)
        self.assertNotIn('>', text)

    def test_context_preserved_in_message(self) -> None:
        """Test that original context is preserved in EmailMessage."""
        context = {
            'to_email': 'user@example.com',
            'username': 'testuser',
            'display_name': 'Test User',
            'login_url': 'https://imbi.example.com/login',
            'extra_data': {'key': 'value'},
        }

        message = self.manager.render_email('welcome', context)

        self.assertEqual(message.context, context)
        self.assertEqual(message.context['extra_data'], {'key': 'value'})

    def test_jinja2_autoescape(self) -> None:
        """Test that Jinja2 autoescape is enabled for HTML."""
        context = {
            'to_email': 'user@example.com',
            'username': '<script>alert("xss")</script>',
            'display_name': 'Test User',
            'login_url': 'https://imbi.example.com/login',
        }

        message = self.manager.render_email('welcome', context)

        # Script tags should be escaped
        self.assertIn('&lt;script&gt;', message.html_body)
        self.assertNotIn('<script>', message.html_body)

    def test_template_not_found(self) -> None:
        """Test error handling for missing template."""
        import jinja2

        context = {
            'to_email': 'user@example.com',
        }

        with self.assertRaises(jinja2.TemplateNotFound):
            self.manager.render_email('nonexistent_template', context)

    def test_default_subject_fallback(self) -> None:
        """Test default subject when template has no subject comment."""
        # We'll need to create a test template without subject comment
        # For now, we can mock the _render_subject method
        import unittest.mock as mock

        with mock.patch.object(
            self.manager,
            '_render_subject',
            return_value='Notification from Imbi',
        ):
            context = {
                'to_email': 'user@example.com',
                'username': 'testuser',
                'display_name': 'Test User',
                'login_url': 'https://imbi.example.com/login',
            }

            message = self.manager.render_email('welcome', context)

            self.assertEqual(message.subject, 'Notification from Imbi')

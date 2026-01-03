"""Jinja2 template management for email rendering."""

import html as html_module
import logging
import pathlib
import re
import typing

import jinja2

from . import models

LOGGER = logging.getLogger(__name__)


class TemplateManager:
    """Manages Jinja2 email templates with HTML and plain text rendering.

    The TemplateManager is a singleton that loads email templates from the
    templates directory and renders them with context variables. It supports
    both HTML and plain text versions of emails, with automatic HTML-to-text
    conversion as a fallback.

    """

    _instance: typing.ClassVar[typing.Optional['TemplateManager']] = None

    def __init__(self) -> None:
        template_dir = pathlib.Path(__file__).parent / 'templates'
        self._env = jinja2.Environment(
            loader=jinja2.FileSystemLoader(str(template_dir)),
            autoescape=jinja2.select_autoescape(['html', 'xml']),
            trim_blocks=True,
            lstrip_blocks=True,
        )

        # Add custom filters
        self._env.filters['strip_html'] = self._html_to_text

    @classmethod
    def get_instance(cls) -> 'TemplateManager':
        """Get the singleton TemplateManager instance.

        Returns:
            The singleton TemplateManager instance.

        """
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def render_email(
        self,
        template_name: str,
        context: dict[str, typing.Any],
    ) -> models.EmailMessage:
        """Render an email template to HTML and plain text.

        Args:
            template_name: Name of template (without extension)
            context: Template context variables (must include 'to_email')

        Returns:
            EmailMessage with rendered HTML and text bodies

        Raises:
            KeyError: If 'to_email' not in context
            jinja2.TemplateNotFound: If template doesn't exist

        """
        if 'to_email' not in context:
            raise KeyError('context must include "to_email"')

        # Render subject
        subject = self._render_subject(template_name, context)

        # Render HTML body
        html_template = self._env.get_template(f'{template_name}.html')
        html_body = html_template.render(**context)

        # Render plain text body
        try:
            text_template = self._env.get_template(f'{template_name}.txt')
            text_body = text_template.render(**context)
        except jinja2.TemplateNotFound:
            # Auto-generate from HTML if text template doesn't exist
            LOGGER.debug(
                'No text template for %s, auto-generating from HTML',
                template_name,
            )
            text_body = self._html_to_text(html_body)

        return models.EmailMessage(
            to_email=context['to_email'],
            subject=subject,
            html_body=html_body,
            text_body=text_body,
            template_name=template_name,
            context=context,
        )

    def _render_subject(
        self,
        template_name: str,
        context: dict[str, typing.Any],
    ) -> str:
        """Render subject line from template comment or default.

        Looks for a comment at the top of the HTML template in the format:
        {# subject: Your subject line with {{ variables }} #}

        Args:
            template_name: Name of template (without extension)
            context: Template context variables

        Returns:
            Rendered subject line

        """
        try:
            # Get template source from loader
            if self._env.loader is None:
                return 'Notification from Imbi'

            source, _, _ = self._env.loader.get_source(
                self._env,
                f'{template_name}.html',
            )

            # Look for {# subject: ... #} comment at top of template
            match = re.search(
                r'\{#\s*subject:\s*(.+?)\s*#\}',
                source,
                re.IGNORECASE,
            )

            if match:
                subject_template = match.group(1)
                rendered: str = jinja2.Template(subject_template).render(
                    **context
                )
                return rendered

        except (
            jinja2.TemplateNotFound,
            jinja2.TemplateSyntaxError,
            AttributeError,
        ) as err:
            LOGGER.warning(
                'Failed to extract subject from %s: %s',
                template_name,
                err,
            )

        # Default subject
        return 'Notification from Imbi'

    def _html_to_text(self, html: str) -> str:
        """Convert HTML to plain text.

        This is a simple conversion that:
        - Removes script and style elements
        - Converts <br> tags to newlines
        - Converts block-level closing tags to double newlines
        - Strips all other HTML tags
        - Decodes HTML entities
        - Normalizes whitespace

        Args:
            html: HTML string to convert

        Returns:
            Plain text version of HTML

        """
        # Remove script and style elements
        text = re.sub(
            r'<(script|style)[^>]*>.*?</\1>',
            '',
            html,
            flags=re.DOTALL | re.IGNORECASE,
        )

        # Replace <br> with newlines
        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)

        # Replace </p>, </div>, </h*>, </li> with double newlines
        text = re.sub(
            r'</(p|div|h[1-6]|li)>',
            '\n\n',
            text,
            flags=re.IGNORECASE,
        )

        # Remove all other tags
        text = re.sub(r'<[^>]+>', '', text)

        # Decode HTML entities
        text = html_module.unescape(text)

        # Normalize whitespace
        text = re.sub(r'\n\s*\n\s*\n+', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)

        return text.strip()

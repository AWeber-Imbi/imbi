"""Dynamic system prompt builder for the Slack bot."""

import logging
import pathlib

from imbi_slackbot import identity, links, settings

LOGGER = logging.getLogger(__name__)

_PROMPT_PATH = pathlib.Path(__file__).parent / 'system_prompt.md'
_prompt_template: str | None = None


def _load_template() -> str:
    """Load the system prompt template from disk.

    Falls back to ``IMBI_SLACKBOT_SYSTEM_PROMPT`` if set.

    Returns:
        The prompt template string with format placeholders.

    """
    global _prompt_template
    if _prompt_template is not None:
        return _prompt_template

    slackbot_settings = settings.get_slackbot_settings()
    if slackbot_settings.system_prompt:
        _prompt_template = slackbot_settings.system_prompt
        return _prompt_template

    _prompt_template = _PROMPT_PATH.read_text(encoding='utf-8')
    return _prompt_template


def build_system_prompt(
    user: identity.ImbiUser,
    tool_names: list[str],
) -> str:
    """Build a dynamic system prompt for the resolved Slack user.

    Args:
        user: The resolved Imbi user.
        tool_names: Names of tools available to this user.

    Returns:
        The system prompt string.

    """
    if tool_names:
        tools_list = ', '.join(tool_names)
        tools_section = (
            f'Available tools: {tools_list}. '
            'Use them to look up real data when answering questions.'
        )
    else:
        tools_section = (
            'You have NO tools available. You cannot look up live data '
            'from Imbi. Answer general questions about Imbi concepts, or '
            'direct the user to the Imbi UI for data queries.'
        )

    base_url = settings.get_slackbot_settings().ui_url
    patterns = links.get_url_patterns()
    if base_url:
        links_section = (
            f'The Imbi UI is at {base_url}. Link to a resource with Slack '
            f'link syntax — <{base_url}/projects/123|project name> — by '
            'appending one of these paths to the base URL:'
            f'\n\n{patterns}'
        )
    else:
        links_section = (
            'Imbi UI paths for pointing the user at a page (no base URL is '
            f'configured, so mention the path):\n\n{patterns}'
        )

    template = _load_template()
    try:
        return template.format(
            display_name=user.display_name,
            email=user.email,
            admin_flag='  [Admin]' if user.is_admin else '',
            tools_section=tools_section,
            links_section=links_section,
        )
    except (KeyError, ValueError, IndexError):
        # An operator-supplied override with stray/unescaped braces would
        # otherwise break prompt construction for every event. Fall back
        # to the unformatted template rather than failing the request.
        LOGGER.exception('Failed to format system prompt template')
        return template

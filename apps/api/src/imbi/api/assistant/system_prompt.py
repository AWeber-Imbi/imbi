"""Dynamic system prompt builder for the AI assistant."""

import pathlib

from imbi_api.assistant import settings
from imbi_api.auth import permissions

_PROMPT_PATH = pathlib.Path(__file__).parent / 'system_prompt.md'
_PROMPT_TEMPLATE: str | None = None


def _load_template() -> str:
    """Load the system prompt template from disk.

    Falls back to IMBI_ASSISTANT_SYSTEM_PROMPT env var if the
    markdown file is missing.

    Returns:
        The prompt template string with format placeholders.

    """
    global _PROMPT_TEMPLATE
    if _PROMPT_TEMPLATE is not None:
        return _PROMPT_TEMPLATE

    assistant_settings = settings.get_assistant_settings()
    if assistant_settings.system_prompt:
        _PROMPT_TEMPLATE = assistant_settings.system_prompt
        return _PROMPT_TEMPLATE

    _PROMPT_TEMPLATE = _PROMPT_PATH.read_text(encoding='utf-8')
    return _PROMPT_TEMPLATE


def build_system_prompt(
    auth: permissions.AuthContext,
    tool_names: list[str],
) -> str:
    """Build a dynamic system prompt based on user context.

    Loads the template from ``system_prompt.md`` (next to this
    module) and fills in user-specific placeholders. The template
    can be overridden via ``IMBI_ASSISTANT_SYSTEM_PROMPT``.

    Args:
        auth: The authenticated user's context.
        tool_names: Names of tools available to this user.

    Returns:
        The system prompt string.

    """
    user = auth.require_user
    perms = sorted(auth.permissions)

    tools_section = ''
    if tool_names:
        tools_list = ', '.join(tool_names)
        tools_section = (
            f'Available tools: {tools_list}. '
            'Use them to look up real data when answering '
            'questions.'
        )

    perms_section = ''
    if perms:
        perms_list = ', '.join(perms)
        perms_section = f'User permissions: {perms_list}.'

    template = _load_template()
    return template.format(
        display_name=user.display_name,
        email=user.email,
        admin_flag='  [Admin]' if user.is_admin else '',
        perms_section=perms_section,
        tools_section=tools_section,
    )

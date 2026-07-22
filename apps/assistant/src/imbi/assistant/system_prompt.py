"""Dynamic system prompt builder for the AI assistant."""

import pathlib

from imbi.assistant import auth, links, settings

_PROMPT_PATH = pathlib.Path(__file__).parent / 'system_prompt.md'
_prompt_template: str | None = None


def _load_template() -> str:
    """Load the system prompt template from disk.

    Falls back to IMBI_ASSISTANT_SYSTEM_PROMPT env var if the
    markdown file is missing.

    Returns:
        The prompt template string with format placeholders.

    """
    global _prompt_template
    if _prompt_template is not None:
        return _prompt_template

    assistant_settings = settings.get_assistant_settings()
    if assistant_settings.system_prompt:
        _prompt_template = assistant_settings.system_prompt
        return _prompt_template

    _prompt_template = _PROMPT_PATH.read_text(encoding='utf-8')
    return _prompt_template


def build_system_prompt(
    auth_context: auth.AuthContext,
    tool_names: list[str],
) -> str:
    """Build a dynamic system prompt based on user context.

    Loads the template from ``system_prompt.md`` (next to this
    module) and fills in user-specific placeholders. The template
    can be overridden via ``IMBI_ASSISTANT_SYSTEM_PROMPT``.

    Args:
        auth_context: The authenticated user's context.
        tool_names: Names of tools available to this user.

    Returns:
        The system prompt string.

    """
    user = auth_context.require_user
    perms = sorted(auth_context.permissions)

    tools_section = ''
    if tool_names:
        tools_list = ', '.join(tool_names)
        tools_section = (
            f'Available tools: {tools_list}. '
            'Use them to look up real data when answering '
            'questions.'
        )
    else:
        tools_section = (
            'You have NO tools available. You cannot look up '
            'live data from Imbi. Answer general questions about '
            'Imbi concepts, or direct the user to the Imbi UI '
            'for data queries.'
        )

    perms_section = ''
    if perms:
        perms_list = ', '.join(perms)
        perms_section = f'User permissions: {perms_list}.'

    base_url = settings.get_assistant_settings().ui_url
    patterns = links.get_url_patterns()
    if base_url:
        links_section = (
            f'The Imbi UI is at {base_url}. When you mention a project, '
            'team, or other resource, link to its page by appending one of '
            f'these paths to that base URL (e.g. {base_url}/projects/123):'
            f'\n\n{patterns}'
        )
    else:
        links_section = (
            'Imbi UI paths (relative to the UI root) for pointing the user '
            f'at a page:\n\n{patterns}'
        )

    template = _load_template()
    return template.format(
        display_name=user.display_name,
        email=user.email,
        admin_flag='  [Admin]' if user.is_admin else '',
        perms_section=perms_section,
        tools_section=tools_section,
        links_section=links_section,
    )

"""Dynamic system prompt builder for the AI assistant.

The template comes from the prompt CMS (``IMBI_ASSISTANT_PROMPT_REF``,
default ``imbi-assistant/system@stable``). When the CMS has no usable
version, the template packaged in :mod:`imbi.common.prompts` is used.
``IMBI_ASSISTANT_SYSTEM_PROMPT`` overrides both; it uses Jinja syntax,
for example ``{{ display_name }}``.
"""

from imbi.assistant import auth, links, settings
from imbi.common import graph
from imbi.common.prompts import system


def _variables(
    auth_context: auth.AuthContext, tool_names: list[str]
) -> dict[str, str]:
    """Build the template variables for the current user."""
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

    return {
        'display_name': user.display_name,
        'email': user.email,
        'admin_flag': '  [Admin]' if user.is_admin else '',
        'perms_section': perms_section,
        'tools_section': tools_section,
        'links_section': links_section,
    }


async def build_system_prompt(
    db: graph.Graph,
    auth_context: auth.AuthContext,
    tool_names: list[str],
) -> system.SystemPrompt:
    """Build the system prompt for the current user.

    Args:
        db: The graph, for reading the prompt from the CMS.
        auth_context: The authenticated user's context.
        tool_names: Names of tools available to this user.

    Returns:
        The rendered prompt with the model settings of its version.

    """
    assistant_settings = settings.get_assistant_settings()
    return await system.load_system_prompt(
        db,
        assistant_settings.prompt_ref,
        _variables(auth_context, tool_names),
        system.ASSISTANT,
        override=assistant_settings.system_prompt,
    )

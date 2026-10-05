"""Dynamic system prompt builder for the Slack bot.

The template comes from the prompt CMS (``IMBI_SLACKBOT_PROMPT_REF``,
default ``imbi-slackbot/system@stable``). When the CMS has no usable
version, the template packaged in :mod:`imbi.common.prompts` is used.
``IMBI_SLACKBOT_SYSTEM_PROMPT`` overrides both; it uses Jinja syntax,
for example ``{{ display_name }}``. A prompt that fails to render never
fails an event: the packaged prompt is used instead.
"""

from imbi.common.prompts import system
from imbi.slackbot import identity, links, settings


def _variables(
    user: identity.ImbiUser, tool_names: list[str]
) -> dict[str, str]:
    """Build the template variables for the resolved Slack user."""
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

    return {
        'display_name': user.display_name,
        'email': user.email,
        'admin_flag': '  [Admin]' if user.is_admin else '',
        'tools_section': tools_section,
        'links_section': links_section,
    }


async def build_system_prompt(
    user: identity.ImbiUser,
    tool_names: list[str],
) -> system.SystemPrompt:
    """Build the system prompt for the resolved Slack user.

    Args:
        user: The resolved Imbi user.
        tool_names: Names of tools available to this user.

    Returns:
        The rendered prompt with the model settings of its version.

    """
    slackbot_settings = settings.get_slackbot_settings()
    return await system.load_system_prompt(
        identity.get_graph(),
        slackbot_settings.prompt_ref,
        _variables(user, tool_names),
        system.SLACKBOT,
        override=slackbot_settings.system_prompt,
    )

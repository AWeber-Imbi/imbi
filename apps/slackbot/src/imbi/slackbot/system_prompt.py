"""Dynamic system prompt builder for the Slack bot.

The template comes from the prompt CMS (``IMBI_SLACKBOT_PROMPT_REF``,
default ``imbi-slackbot/system@stable``). When the CMS has no usable
version, the template packaged in :mod:`imbi.common.prompts` is used.
``IMBI_SLACKBOT_SYSTEM_PROMPT`` overrides both; it uses Jinja syntax,
for example ``{{ display_name }}``. A prompt that fails to render never
fails an event: the packaged prompt is used instead.
"""

import collections.abc
import dataclasses

from imbi.common import models
from imbi.common.prompts import skills, system
from imbi.slackbot import identity, links, settings


def _variables(
    user: identity.ImbiUser, tool_names: list[str]
) -> dict[str, str]:
    """Build the template variables for the resolved Slack user."""
    if tool_names:
        tools_list = ', '.join(tool_names)
        # The tools reach every organization of the user; this Slack
        # workspace belongs to one.
        tools_section = (
            f'Available tools: {tools_list}. '
            'Use them to look up real data when answering questions. '
            f'Work only in the organization `{user.org_slug}`: use it as '
            'the org_slug of every tool call.'
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


def workspace_org(user: identity.ImbiUser) -> str | None:
    """The organization of the Slack workspace, which the model of a turn
    must belong to (#1027). ``None`` before the user carries it: each
    organization of the user."""
    # ImbiUser.org_slug comes with #1042; read it directly once this
    # branch is on top of it.
    return getattr(user, 'org_slug', None)


async def build_system_prompt(
    user: identity.ImbiUser,
    tool_names: list[str],
    skill_list: collections.abc.Sequence[models.Prompt] = (),
) -> system.SystemPrompt:
    """Build the system prompt for the resolved Slack user.

    Args:
        user: The resolved Imbi user.
        tool_names: Names of tools available to this user.
        skill_list: The skills, listed after the rendered prompt so that
            every prompt source (override, CMS, packaged) gets them.

    Returns:
        The rendered prompt with the model settings of its version.

    """
    slackbot_settings = settings.get_slackbot_settings()
    prompt = await system.load_system_prompt(
        identity.get_graph(),
        slackbot_settings.prompt_ref,
        _variables(user, tool_names),
        system.SLACKBOT,
        override=slackbot_settings.system_prompt,
        email=user.email,
        org_slug=workspace_org(user),
    )
    return dataclasses.replace(
        prompt, text=prompt.text + skills.catalog(skill_list)
    )

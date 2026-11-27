"""Skills: the prompts of the ``mcp-skills`` namespace, served with the
MCP Skills extension (SEP-2640).

Each generative prompt in :data:`NAMESPACE` is one skill when its
``stable`` label (else its default label) points at a version. The slug
is the skill name, the description tells the client when to use the
skill, and the system template of that version is the body of
``SKILL.md``. The template is not rendered: rendering needs an
organization, and the client gives the skill its input in the
conversation.

The prompts are read from the Imbi API with the caller's credentials,
so a caller without ``prompt:read`` gets no skills.
"""

import asyncio
import logging
import typing

import fastmcp.skills
import httpx2
from fastmcp.skills import provider

LOGGER = logging.getLogger(__name__)

NAMESPACE = 'mcp-skills'

LABEL = 'stable'

#: The longest description that the Skills extension accepts.
MAX_DESCRIPTION = 1024

type Body = dict[str, typing.Any]


def _version(prompt: Body) -> int | None:
    """The version that ``stable``, else the default label, points at."""
    by_name = {label['name']: label['version'] for label in prompt['labels']}
    return by_name.get(LABEL) or by_name.get(prompt['default_label'])


class PromptSkills(provider.SkillCatalogProvider):
    """Serve the :data:`NAMESPACE` prompts as skills.

    ``load_skills`` runs once per MCP request that reads skills.

    Args:
        client: The Imbi API client, which sends the caller's
            Authorization header.
        prefix: The mount prefix of the API routes.

    """

    def __init__(self, client: httpx2.AsyncClient, prefix: str) -> None:
        super().__init__()
        self._client = client
        self._path = f'{prefix}/prompts'

    async def load_skills(self) -> list[fastmcp.skills.Skill]:
        """The skills that the caller can read. Never raises."""
        try:
            response = await self._client.get(
                f'{self._path}/', params={'namespace': NAMESPACE}
            )
            if response.status_code == int(httpx2.codes.FORBIDDEN):
                return []
            response.raise_for_status()
            prompts: list[Body] = response.json()
        except (httpx2.HTTPError, ValueError):
            LOGGER.warning('Could not list the skills', exc_info=True)
            return []
        skills = await asyncio.gather(
            *(
                self._skill(prompt, version)
                for prompt in prompts
                if prompt.get('kind') == 'generative'
                and prompt.get('archived_at') is None
                and (version := _version(prompt)) is not None
            )
        )
        return [skill for skill in skills if skill is not None]

    async def _skill(
        self, prompt: Body, version: int
    ) -> fastmcp.skills.Skill | None:
        """The skill of one prompt, or ``None`` when it is not valid."""
        slug = prompt['slug']
        try:
            response = await self._client.get(
                f'{self._path}/{NAMESPACE}/{slug}/versions/{version}'
            )
            response.raise_for_status()
            system = response.json()['system']
            description = ' '.join(
                (prompt.get('description') or prompt['name']).split()
            )
            return fastmcp.skills.Skill(
                name=slug,
                description=description[:MAX_DESCRIPTION],
                instructions=system,
            )
        except (httpx2.HTTPError, ValueError, KeyError):
            # ValueError includes a slug that is not a valid skill name.
            LOGGER.warning('Could not load the skill %s', slug, exc_info=True)
            return None

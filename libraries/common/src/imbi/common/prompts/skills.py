"""Skills: prompts that a consumer's model loads on demand.

A skill is a generative prompt in the :data:`NAMESPACE` namespace of the
prompt CMS. The consumer adds :func:`catalog` (the slug and description
of each skill) to its system prompt and gives the model the
:data:`TOOL` tool. When the model calls the tool, :func:`execute`
renders the version that the ``stable`` label (else the default label)
points at, and returns the text as the tool result. A version that
declares the ``arguments`` variable gets the arguments of the call.
"""

import collections.abc
import logging
import typing

from imbi.common import graph, models
from imbi.common.prompts import namespaces, rendering, resolve

LOGGER = logging.getLogger(__name__)

NAMESPACE = namespaces.SKILLS

LABEL = 'stable'

TOOL_NAME = 'skill_invoke'

#: The longest description put in the system prompt, in characters.
MAX_DESCRIPTION = 300

TOOL: dict[str, typing.Any] = {
    'name': TOOL_NAME,
    'description': (
        'Load the full instructions of a skill from the skills list in '
        'the system prompt. Follow the instructions that it returns.'
    ),
    'input_schema': {
        'type': 'object',
        'properties': {
            'name': {
                'type': 'string',
                'description': 'The slug of the skill.',
            },
            'arguments': {
                'type': 'string',
                'description': 'Optional input for the skill.',
            },
        },
        'required': ['name'],
    },
}


async def list_skills(db: graph.Graph | None) -> list[models.Prompt]:
    """Return the skills, sorted by slug.

    Errors are logged, never raised, so that a turn does not fail when
    the skills cannot be read.
    """
    if db is None:
        return []
    try:
        records = await db.execute(
            resolve.LIST_NAMESPACE_QUERY,
            {'namespace': NAMESPACE},
            ['p', 'latest'],
        )
        prompts = [
            resolve.parse_prompt(props)
            for record in records
            if (props := resolve.vertex_props(record['p'])) is not None
        ]
    except Exception:  # noqa: BLE001 - a turn must never fail on this
        LOGGER.warning('Failed to list the skills', exc_info=True)
        return []
    # Only a promoted skill is listed: the description goes into every
    # user's system prompt, and a prompt:create holder can write one
    # without a label.
    return sorted(
        (p for p in prompts if p.kind == 'generative' and _label(p)),
        key=lambda p: p.slug,
    )


def _label(prompt: models.Prompt) -> models.PromptLabel | None:
    """The label :func:`invoke` uses: ``stable``, else the default."""
    by_name = {label.name: label for label in prompt.labels}
    return by_name.get(LABEL) or by_name.get(prompt.default_label)


def _summary(prompt: models.Prompt) -> str:
    """The description on one line, capped at :data:`MAX_DESCRIPTION`."""
    text = ' '.join((prompt.description or prompt.name).split())
    return text[:MAX_DESCRIPTION]


def catalog(skills: collections.abc.Sequence[models.Prompt]) -> str:
    """Return the system prompt section that lists ``skills`` and tells
    the model how to write one, with the blank line that separates it
    from the text before it."""
    if skills:
        lines = '\n'.join(f'- **{s.slug}**: {_summary(s)}' for s in skills)
        listed = (
            'Each skill below says when to use it. When a request matches '
            f'a skill, call `{TOOL_NAME}` with its slug to load its '
            f'instructions before you answer.\n\n{lines}'
        )
    else:
        listed = 'There are no skills yet.'
    return (
        f'\n\n## Skills\n\n{listed}\n\n'
        'When the user asks you to create or change a skill, use the Imbi '
        f'prompt tools on a prompt in the `{NAMESPACE}` namespace. The '
        'slug is the skill name (kebab-case). The description says when '
        'to use the skill. The system template holds the instructions; '
        'to take input, declare the `arguments` variable and use '
        f'`{{{{ arguments }}}}`. A skill is used only after its `{LABEL}` '
        'label points at a version; if the user cannot set labels, tell '
        'them that an admin must promote the version.'
    )


async def invoke(db: graph.Graph, slug: str, arguments: str = '') -> str:
    """Render the skill ``slug`` and return its text.

    Raises:
        resolve.PromptError: The skill does not exist or has no usable
            version.
        rendering.RenderError: The skill does not render.

    """
    # The slug comes from the model, so it is never parsed as a
    # reference: a selector in it must not pick another version.
    prompt, _latest = await resolve.fetch_prompt(db, NAMESPACE, slug)
    if prompt.archived_at is not None or prompt.kind != 'generative':
        raise resolve.PromptNotFound(f'Skill {slug} not found')
    label = _label(prompt)
    if label is None:
        raise resolve.PromptNotFound(f'Skill {slug} has no {LABEL} version')
    version = await resolve.fetch_version(db, prompt, label.version)
    variables = (
        {'arguments': arguments}
        if 'arguments' in version.variable_schema
        else {}
    )
    rendered = await rendering.render(version, variables, {})
    return rendered.system


async def execute(
    db: graph.Graph | None, tool_input: dict[str, typing.Any]
) -> tuple[str, bool]:
    """Run a :data:`TOOL` call; return ``(text, is_error)``.

    A failure is a tool error, never a failed turn.
    """
    if db is None:
        return 'ERROR: skills are not available right now.', True
    try:
        text = await invoke(
            db,
            str(tool_input.get('name', '')),
            str(tool_input.get('arguments') or ''),
        )
    except (resolve.PromptError, rendering.RenderError) as exc:
        return f'ERROR: {exc}', True
    except Exception:  # a turn must never fail on this
        LOGGER.exception('Failed to invoke a skill')
        return 'ERROR: the skill could not be loaded right now.', True
    return text, False

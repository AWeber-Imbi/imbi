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
from imbi.common.prompts import rendering, resolve

LOGGER = logging.getLogger(__name__)

NAMESPACE = 'imbi-skills'

LABEL = 'stable'

TOOL_NAME = 'skill_invoke'

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
    except Exception:  # noqa: BLE001 - a turn must never fail on this
        LOGGER.warning('Failed to list the skills', exc_info=True)
        return []
    prompts = [
        resolve.parse_prompt(props)
        for record in records
        if (props := resolve.vertex_props(record['p'])) is not None
    ]
    return sorted(
        (p for p in prompts if p.kind == 'generative'),
        key=lambda p: p.slug,
    )


def catalog(skills: collections.abc.Sequence[models.Prompt]) -> str:
    """Return the system prompt section that lists ``skills``, with the
    blank line that separates it from the text before it."""
    if not skills:
        return ''
    lines = [f'- **{s.slug}**: {s.description or s.name}' for s in skills]
    return (
        '\n\n## Skills\n\nAvailable skills:\n'
        + '\n'.join(lines)
        + f'\n\nWhen a request matches a skill, call `{TOOL_NAME}` with '
        'its slug to load its instructions before you answer.'
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
    by_name = {label.name: label for label in prompt.labels}
    label = by_name.get(LABEL) or by_name.get(prompt.default_label)
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
    return text, False

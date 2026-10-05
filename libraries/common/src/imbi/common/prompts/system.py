"""Give a prompt consumer its system prompt, with a built-in fallback.

A consumer such as imbi-assistant names a prompt by reference
(``imbi-assistant/system@stable``) and passes its template variables.
The order is: an operator override (an environment setting), then the
prompt CMS, then the template packaged with Imbi. Every path renders
through the same sandbox (:mod:`.rendering`).

A failure in the CMS path (no such prompt, a render error, a graph
error) is logged and the packaged template is used, so a broken or
missing prompt never fails a turn.
"""

import collections.abc
import dataclasses
import functools
import importlib.resources
import logging
import typing

from imbi.common import graph, models
from imbi.common.prompts import rendering, resolve

LOGGER = logging.getLogger(__name__)

#: The provider driver whose models the consumers can call.
_SUPPORTED_DRIVER = 'anthropic'

Source = typing.Literal['cms', 'fallback', 'override']


@dataclasses.dataclass(frozen=True)
class DefaultPrompt:
    """A prompt Imbi ships, used as the fallback and as seed data."""

    namespace: str
    slug: str
    name: str
    description: str
    template: str
    variables: tuple[str, ...]
    type: str = 'core_system'

    @property
    def ref(self) -> str:
        return f'{self.namespace}/{self.slug}'

    def variable_schema(self) -> dict[str, models.PromptVariable]:
        return {
            name: models.PromptVariable(type='str', required=True)
            for name in self.variables
        }

    def text(self) -> str:
        return default_template(self.template)


ASSISTANT = DefaultPrompt(
    namespace='imbi-assistant',
    slug='system',
    name='Assistant system prompt',
    description='System prompt for the Imbi assistant.',
    template='imbi-assistant-system.md',
    variables=(
        'display_name',
        'email',
        'admin_flag',
        'perms_section',
        'tools_section',
        'links_section',
    ),
)

SLACKBOT = DefaultPrompt(
    namespace='imbi-slackbot',
    slug='system',
    name='Slackbot system prompt',
    description='System prompt for the Imbi Slack bot.',
    template='imbi-slackbot-system.md',
    variables=(
        'display_name',
        'email',
        'admin_flag',
        'tools_section',
        'links_section',
    ),
)

DEFAULT_PROMPTS: tuple[DefaultPrompt, ...] = (ASSISTANT, SLACKBOT)


@functools.cache
def default_template(filename: str) -> str:
    """Return a template packaged in ``imbi.common.prompts.defaults``."""
    return (
        importlib.resources.files('imbi.common.prompts')
        .joinpath('defaults', filename)
        .read_text(encoding='utf-8')
    )


@dataclasses.dataclass(frozen=True)
class SystemPrompt:
    """A rendered system prompt and the settings that came with it."""

    text: str
    source: Source
    #: ``namespace/slug@n`` when the text came from the CMS.
    ref: str | None = None
    #: Set only when the version names an enabled catalog model that a
    #: supported (Anthropic) provider serves.
    model_id: str | None = None
    max_tokens: int | None = None
    temperature: float | None = None


async def _render(
    template: str,
    variables: collections.abc.Mapping[str, str],
) -> str:
    """Render a template that is not stored in the CMS."""
    version = models.PromptVersion(
        prompt=models.Prompt(name='', slug='local', namespace='local'),
        prompt_id='local',
        n=1,
        system=template,
        variable_schema={
            name: models.PromptVariable(type='str', required=True)
            for name in variables
        },
        content_sha256='',
        created_by='imbi',
    )
    rendered = await rendering.render(version, variables, {})
    return rendered.system


async def _fallback(
    default: DefaultPrompt,
    variables: collections.abc.Mapping[str, str],
) -> SystemPrompt:
    template = default.text()
    try:
        text = await _render(template, variables)
    except rendering.RenderError:
        # The packaged template is tested, so this is not expected; a
        # raw template is still a better prompt than no prompt.
        LOGGER.exception('Failed to render the packaged %s', default.ref)
        text = template
    return SystemPrompt(text=text, source='fallback')


async def _model_id(
    db: graph.Graph, version: models.PromptVersion, ref: str
) -> str | None:
    """Return the version's model id when the consumer can call it."""
    if version.model is None:
        return None
    info = await resolve.model_info(db, version.model)
    if info is None or not info.enabled:
        LOGGER.warning(
            'Prompt %s names AI model %r, which is missing or disabled; '
            'using the configured model',
            ref,
            version.model,
        )
        return None
    if info.driver != _SUPPORTED_DRIVER:
        LOGGER.warning(
            'Prompt %s names AI model %r, served by driver %r; only %r '
            'is supported here, so the configured model is used',
            ref,
            version.model,
            info.driver,
            _SUPPORTED_DRIVER,
        )
        return None
    return version.model_id or info.model_id


async def load_model_id(db: graph.Graph, ref: str) -> str | None:
    """Return the model id of ``ref``'s version, when a consumer can call it.

    ``None`` when the prompt is missing, names no model, or names one
    that is disabled or served by an unsupported driver. Errors are
    logged, never raised.
    """
    try:
        _prompt, version, _label = await resolve.resolve(db, ref)
        return await _model_id(db, version, ref)
    except resolve.PromptError:
        return None
    except Exception:  # noqa: BLE001 - creating a conversation must not fail
        LOGGER.warning('Failed to read the model of %s', ref, exc_info=True)
        return None


async def load_system_prompt(
    db: graph.Graph | None,
    ref: str,
    variables: collections.abc.Mapping[str, str],
    default: DefaultPrompt,
    *,
    override: str | None = None,
) -> SystemPrompt:
    """Return the consumer's system prompt.

    Parameters:
        db: The graph, or ``None`` when it is not open yet (the
            packaged prompt is used).
        ref: The CMS reference, such as ``imbi-assistant/system@stable``.
        variables: The consumer's template variables. Only the variables
            the version declares are passed to it, so an editor may drop
            one without breaking the render.
        default: The packaged prompt used when the CMS cannot answer.
        override: An operator-supplied template that replaces both.

    """
    if override:
        try:
            return SystemPrompt(
                text=await _render(override, variables), source='override'
            )
        except rendering.RenderError:
            LOGGER.exception(
                'Failed to render the system prompt override for %s; '
                'using the packaged prompt',
                default.ref,
            )
            return await _fallback(default, variables)

    if db is None:
        return await _fallback(default, variables)

    try:
        prompt, version, _label = await resolve.resolve(db, ref)
        declared = {
            name: value
            for name, value in variables.items()
            if name in version.variable_schema
        }
        rendered = await rendering.render(version, declared, {})
        model_id = await _model_id(db, version, ref)
    except resolve.PromptError as e:
        LOGGER.info('Using the packaged prompt for %s: %s', ref, e)
        return await _fallback(default, variables)
    except Exception:  # noqa: BLE001 - a turn must never fail on this
        LOGGER.warning(
            'Failed to load prompt %s from the CMS; using the packaged prompt',
            ref,
            exc_info=True,
        )
        return await _fallback(default, variables)

    return SystemPrompt(
        text=rendered.system,
        source='cms',
        ref=f'{prompt.namespace}/{prompt.slug}@{version.n}',
        model_id=model_id,
        max_tokens=version.params.max_tokens,
        temperature=version.params.temperature,
    )

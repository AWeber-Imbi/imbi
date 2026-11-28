"""Give a prompt consumer its system prompt, with a built-in fallback.

A consumer such as imbi-assistant names a prompt by reference
(``imbi-assistant/system@stable``) and passes its template variables.
The order is: an operator override (an environment setting), then the
prompt CMS, then the template packaged with Imbi. Every path renders
through the same sandbox (:mod:`.rendering`).

A failure in the CMS path (no such prompt, a render error, a graph
error) is logged and the packaged template is used, so a broken or
missing prompt never fails a turn. A version that names a model the
consumer cannot use is a configuration error: it raises
:class:`~imbi.common.llm.resolve.ModelUnusable`.
"""

import collections.abc
import dataclasses
import functools
import importlib.resources
import logging
import typing

from imbi.common import graph, models
from imbi.common.llm import drivers
from imbi.common.llm import resolve as llm_resolve
from imbi.common.prompts import rendering, resolve

LOGGER = logging.getLogger(__name__)

#: The provider drivers whose models the consumers can call.
_DRIVERS = (drivers.ANTHROPIC,)

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

TICKET_SUBJECT = DefaultPrompt(
    namespace='imbi-api',
    slug='ticket-subject',
    name='Ticket subject',
    description='Writes the subject of a new ticket from its description.',
    template='imbi-api-ticket-subject.md',
    variables=(),
)

WORKFLOW_DESCRIPTION = DefaultPrompt(
    namespace='imbi-api',
    slug='workflow-description',
    name='Workflow description',
    description='Writes the description of a workflow when it is saved.',
    template='imbi-api-workflow-description.md',
    variables=(),
)

AGENT_DESCRIPTION = DefaultPrompt(
    namespace='imbi-api',
    slug='agent-description',
    name='Agent description',
    description='Writes the description of an agent when it is saved.',
    template='imbi-api-agent-description.md',
    variables=(),
)

DEFAULT_PROMPTS: tuple[DefaultPrompt, ...] = (
    ASSISTANT,
    SLACKBOT,
    TICKET_SUBJECT,
    WORKFLOW_DESCRIPTION,
    AGENT_DESCRIPTION,
)


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
    #: Set when the version names a model. The model is an enabled
    #: catalog model that an enabled Anthropic provider serves, and that
    #: the user may use.
    model_id: str | None = None
    #: The catalog provider of ``model_id``.
    provider: models.AIProvider | None = None
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


class ConsumerModel(typing.NamedTuple):
    """A model id that a consumer sends, and its catalog provider."""

    model_id: str
    provider: models.AIProvider


async def _org_ids(
    db: graph.Graph, email: str, org_id: str | None
) -> list[str]:
    """The organizations of a call for the user ``email``: ``org_id``
    (the organization of the call, whose membership the caller checked)
    when it is set, else each organization of the user."""
    if org_id is not None:
        return [org_id]
    return await resolve.member_org_ids(db, email)


async def default_model(
    db: graph.Graph,
    email: str,
    *,
    admin: bool = False,
    org_id: str | None = None,
) -> ConsumerModel | None:
    """Return the default model for the user ``email``,
    for a consumer whose prompt version names no model.

    The default applies for a call in one organization: ``org_id``, or
    the only organization of the user. The team default needs a team and
    these consumers have none, so the organization default is used.
    ``None``: no default, and the consumer uses its configured model.
    An ``admin`` may use a ``restricted`` model.

    Raises:
        llm_resolve.ModelUnusable: The default model cannot be used, or
            a driver other than Anthropic serves it.

    """
    resolved = await llm_resolve.resolve_model(
        db,
        await _org_ids(db, email, org_id),
        email=email,
        admin=admin,
        drivers=_DRIVERS,
    )
    if resolved.model is None:
        return None
    return ConsumerModel(resolved.model.model_id, resolved.model.provider)


async def request_model(
    db: graph.Graph,
    email: str,
    model_id: str,
    *,
    admin: bool = False,
    org_id: str | None = None,
) -> ConsumerModel | None:
    """Return the catalog model of the vendor ``model_id`` that a request
    names, in the organization ``org_id`` (else in the organizations of
    the user ``email``). ``None`` only when no catalog model has the id;
    a catalog model with the id that cannot be used is an error.

    Raises:
        llm_resolve.ModelUnusable: The model cannot be used, or a driver
            other than Anthropic serves it.

    """
    try:
        resolved = await llm_resolve.resolve_model(
            db,
            await _org_ids(db, email, org_id),
            model_id=model_id,
            email=email,
            admin=admin,
            drivers=_DRIVERS,
        )
    except llm_resolve.ModelUnusable as e:
        if e.reason == 'not_found':
            return None
        raise
    model = typing.cast('models.AIModel', resolved.model)
    return ConsumerModel(model.model_id, model.provider)


async def _model(
    db: graph.Graph,
    version: models.PromptVersion,
    email: str | None,
    org_id: str | None = None,
    admin: bool = False,
) -> ConsumerModel | None:
    """Return the version's model, or ``None`` when the version names no
    model (the consumer then uses the default or its configured model).
    An ``admin`` may use a ``restricted`` model.

    Raises:
        llm_resolve.ModelUnusable: The model is missing, disabled, served
            by a disabled provider or by a driver other than Anthropic,
            or is restricted to teams that do not include the user
            (#788).

    """
    if version.model is None:
        return None
    # The catalog is per organization and these prompts are global, so
    # the model comes from the catalogs of the organizations of the
    # user. Without a user, there is no catalog model.
    if email is None:
        return None
    resolved = await llm_resolve.resolve_model(
        db,
        await _org_ids(db, email, org_id),
        model=version.model,
        email=email,
        admin=admin,
        drivers=_DRIVERS,
    )
    model = typing.cast('models.AIModel', resolved.model)
    # The slug names the model: a run uses the id of the slug in the
    # catalog, not the id stored with a global prompt (ADR 0018).
    return ConsumerModel(model.model_id, model.provider)


async def load_model(
    db: graph.Graph,
    ref: str,
    email: str | None = None,
    *,
    admin: bool = False,
    org_id: str | None = None,
) -> ConsumerModel | None:
    """Return the model of ``ref``'s version, when a consumer can call it
    for the user ``email``. An ``admin`` may use a ``restricted`` model.

    ``None`` when the prompt is missing or names no model. An error that
    reads the prompt is logged, and ``None`` is returned. An error in the
    check of the version's model is raised: no other model is used in
    its place, so a failed spend check cannot skip the cap.

    Raises:
        llm_resolve.ModelUnusable: The version names a model that the
            consumer cannot use.

    """
    try:
        _prompt, version, _label = await resolve.resolve(db, ref)
    except resolve.PromptError:
        return None
    except Exception:  # noqa: BLE001 - creating a conversation must not fail
        LOGGER.warning('Failed to read the prompt %s', ref, exc_info=True)
        return None
    return await _model(db, version, email, org_id, admin)


async def load_system_prompt(
    db: graph.Graph | None,
    ref: str,
    variables: collections.abc.Mapping[str, str],
    default: DefaultPrompt,
    *,
    override: str | None = None,
    email: str | None = None,
    org_id: str | None = None,
    admin: bool = False,
    check_model: bool = True,
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
        email: The user of the turn, for a ``restricted`` model.
        org_id: The organization of the turn, whose membership the
            consumer checked. ``None``: each organization of the user.
        admin: The user is an admin, who may use a ``restricted`` model.
        check_model: ``False`` for a consumer whose turn does not use the
            model of the version. A model that cannot be used is then
            logged, and the prompt is returned without the model
            settings of the version.

    Raises:
        llm_resolve.ModelUnusable: The CMS version names a model that the
            consumer cannot use, and ``check_model`` is set.

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

    # An error in the check of the named model is not a CMS failure: no
    # other model is used in its place (ADR 0018).
    try:
        model = await _model(db, version, email, org_id, admin)
    except Exception:
        if check_model:
            raise
        # The turn does not use this model, so an unusable model or a
        # failed lookup does not change its instructions.
        LOGGER.warning(
            'The model of %s cannot be used; its settings do not apply',
            ref,
            exc_info=True,
        )
        return SystemPrompt(
            text=rendered.system,
            source='cms',
            ref=f'{prompt.namespace}/{prompt.slug}@{version.n}',
        )

    return SystemPrompt(
        text=rendered.system,
        source='cms',
        ref=f'{prompt.namespace}/{prompt.slug}@{version.n}',
        model_id=None if model is None else model.model_id,
        provider=None if model is None else model.provider,
        max_tokens=version.params.max_tokens,
        temperature=version.params.temperature,
    )

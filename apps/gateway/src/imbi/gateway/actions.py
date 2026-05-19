import http
import logging
import typing

import celpy
import httpx
import pydantic
import pydantic_settings
from imbi_common import json_pointer

from imbi_gateway import helpers, version

if typing.TYPE_CHECKING:
    from collections import abc

    from imbi_common.plugins import base as plugin_base


class ActionSettings(pydantic_settings.BaseSettings):
    model_config = {'env_prefix': 'ACTIONS_'}
    imbi_url: pydantic.HttpUrl = pydantic.HttpUrl('http://imbi-api:8000')
    imbi_token: str


LOGGER = logging.getLogger(__name__)


class UpdateProjectRule(pydantic.BaseModel):
    path: typing.Annotated[
        json_pointer.JsonPointer,
        pydantic.Field(
            description='JSON Pointer on the Imbi project to patch.'
        ),
    ]
    from_: typing.Annotated[
        json_pointer.JsonPointer,
        pydantic.Field(
            alias='from',
            description='JSON Pointer on the webhook payload to read.',
        ),
    ]


class UpdateProjectConfig(pydantic.RootModel[list[UpdateProjectRule]]):
    """``WebhookRule.handler_config`` for :func:`update_project`.

    A list of ``{path, from}`` mappings. Each entry resolves
    ``from`` against the webhook body and patches the value into
    ``path`` on the matched Imbi project.
    """

    root: list[UpdateProjectRule] = pydantic.Field(
        default_factory=list,
        description='Ordered list of source/target JSON Pointer mappings.',
    )


class ImbiClient(httpx.AsyncClient):
    def __init__(self) -> None:
        settings = helpers.settings_from_environment(ActionSettings)
        super().__init__(
            base_url=str(settings.imbi_url),
            headers={
                'authorization': f'Bearer {settings.imbi_token}',
                'user-agent': f'imbi-gateway/{version}',
            },
        )

    async def patch_project(
        self,
        org_slug: str,
        project_id: str,
        patch: abc.Iterable[abc.Mapping[str, object]],
    ) -> httpx.Response:
        url = f'/organizations/{org_slug}/projects/{project_id}'
        LOGGER.debug('Patching project %s', url)
        response = await self.patch(url, json=patch)
        if response.is_error:
            try:
                detail = response.json()
            except ValueError:
                detail = response.content
            LOGGER.warning('Failed to patch project %r: %r', url, detail)
        return response

    async def find_user_by_identity(
        self, plugin_slug: str, subject: str
    ) -> str | None:
        """Look up an Imbi user by external identity subject.

        Returns the user's email (the principal identity used by the
        Release ``created_by`` field) or ``None`` when no active
        ``IdentityConnection`` matches.
        """
        response = await self.get(
            '/users/by-identity',
            params={'plugin_slug': plugin_slug, 'subject': subject},
        )
        if response.status_code == http.HTTPStatus.NOT_FOUND:
            return None
        if response.is_error:
            LOGGER.warning(
                'Failed to look up user for plugin=%r subject=%r: %s',
                plugin_slug,
                subject,
                response.text,
            )
            return None
        data = response.json()
        email = data.get('email')
        return str(email) if email else None

    async def create_release(
        self, org_slug: str, project_id: str, body: abc.Mapping[str, object]
    ) -> httpx.Response:
        url = f'/organizations/{org_slug}/projects/{project_id}/releases/'
        LOGGER.debug('Creating release %s', url)
        response = await self.post(url, json=body)
        if response.is_error and (
            response.status_code != http.HTTPStatus.CONFLICT
        ):
            LOGGER.warning(
                'Failed to create release %r: %s', url, response.text
            )
        return response

    async def record_deployment(
        self,
        org_slug: str,
        project_id: str,
        version: str,
        env_slug: str,
        body: abc.Mapping[str, object],
    ) -> httpx.Response:
        url = (
            f'/organizations/{org_slug}/projects/{project_id}'
            f'/releases/{version}/environments/{env_slug}'
        )
        LOGGER.debug('Recording deployment %s', url)
        response = await self.post(url, json=body)
        if response.is_error and (
            response.status_code != http.HTTPStatus.NOT_FOUND
        ):
            LOGGER.warning(
                'Failed to record deployment %r: %s', url, response.text
            )
        return response


class CreateReleaseConfig(pydantic.BaseModel):
    """Validates ``handler_config`` for :func:`create_release`."""

    title_selector: json_pointer.JsonPointer
    version_expression: str
    committish_expression: str


class AddDeploymentEventConfig(pydantic.BaseModel):
    """Validates ``handler_config`` for :func:`add_deployment_event`."""

    environment_selector: json_pointer.JsonPointer
    version_expression: str
    status_selector: json_pointer.JsonPointer
    note_selector: json_pointer.JsonPointer | None = None
    external_run_id_selector: json_pointer.JsonPointer | None = None


# Raw deployment-status state -> Imbi _DEPLOYMENT_STATUS literal.
# The selector decides where the state is read from; this map is the
# static translation from GitHub-style vocabulary to Imbi's enum.
# Unknown states are logged and skipped (no event recorded).
_STATUS_MAP: dict[str, str] = {
    'queued': 'pending',
    'pending': 'pending',
    'in_progress': 'in_progress',
    'success': 'success',
    'failure': 'failed',
    'error': 'failed',
    'inactive': 'rolled_back',
}


def _cel_substring(
    string: celpy.celtypes.StringType,
    start: celpy.celtypes.IntType,
    end: celpy.celtypes.IntType | None = None,
) -> celpy.celtypes.StringType:
    if end is None:
        return celpy.celtypes.StringType(string[int(start) :])
    return celpy.celtypes.StringType(string[int(start) : int(end)])


_CEL_FUNCTIONS: dict[str, celpy.CELFunction] = {'substring': _cel_substring}


def _evaluate_cel(expression: str, body: object) -> str:
    env = celpy.Environment()
    program = env.program(env.compile(expression), functions=_CEL_FUNCTIONS)
    return str(program.evaluate(celpy.json_to_cel(body)))


async def update_project(
    *,
    ctx: plugin_base.PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: UpdateProjectConfig,
    payload: object,
) -> None:
    """Patch the matched Imbi project with values pulled from the payload.

    Patch attribution is the gateway's service token, so
    ``ctx.actor_user_id`` and ``credentials`` are unused here.
    ``action_config`` arrives pre-validated as
    :class:`UpdateProjectConfig`.
    """
    del credentials, external_identifier
    LOGGER.info('Updating project /%s/%s', ctx.org_slug, ctx.project_id)
    LOGGER.info('%r', action_config.root)
    patch = [
        {
            'op': 'add',
            'path': str(update.path),
            'value': update.from_.resolve(payload),
        }
        for update in action_config.root
    ]
    async with ImbiClient() as client:
        await client.patch_project(ctx.org_slug, ctx.project_id, patch)


async def create_release(
    *,
    ctx: plugin_base.PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: CreateReleaseConfig,
    payload: object,
) -> None:
    """Processes a deployment notification and ensures the release exists.

    The tag is the result of evaluating the CEL ``version_expression``
    against ``payload``; the committish is the result of evaluating the
    CEL ``committish_expression`` (typically ``substring(deployment.sha,
    0, 7)``; the title is taken from the JSONPointer ``title_selector``.
    ``ctx.actor_user_id`` (the resolved Imbi user's email) is passed
    as ``created_by`` when present; otherwise the API defaults to the
    gateway's service principal. ``action_config`` arrives pre-validated.
    """
    del credentials, external_identifier
    version_value = _evaluate_cel(action_config.version_expression, payload)
    committish_value = _evaluate_cel(
        action_config.committish_expression, payload
    )
    create_body: dict[str, object] = {
        'tag': version_value,
        'committish': committish_value,
        'title': str(action_config.title_selector.resolve(payload)),
    }
    if ctx.actor_user_id is not None:
        create_body['created_by'] = ctx.actor_user_id
    async with ImbiClient() as client:
        response = await client.create_release(
            ctx.org_slug, ctx.project_id, create_body
        )
    if response.status_code == http.HTTPStatus.CONFLICT:
        LOGGER.debug(
            'Release %r already exists for project %s',
            version_value,
            ctx.project_id,
        )


async def add_deployment_event(
    *,
    ctx: plugin_base.PluginContext,
    credentials: dict[str, str],
    external_identifier: str,
    action_config: AddDeploymentEventConfig,
    payload: object,
) -> None:
    """Processes a deployment_status notification.

    Appends a deployment event to the release's DEPLOYED_TO edge for
    the matching environment. ``record_deployment`` has no
    ``created_by`` field so ``ctx.actor_user_id`` is unused here.
    """
    del credentials, external_identifier
    raw_state = str(action_config.status_selector.resolve(payload))
    status = _STATUS_MAP.get(raw_state)
    if status is None:
        LOGGER.warning('Unmapped deployment status %r — skipping', raw_state)
        return
    version_value = _evaluate_cel(action_config.version_expression, payload)
    environment = str(action_config.environment_selector.resolve(payload))
    event_body: dict[str, object] = {'status': status}
    if action_config.note_selector is not None:
        event_body['note'] = str(action_config.note_selector.resolve(payload))
    if action_config.external_run_id_selector is not None:
        event_body['external_run_id'] = str(
            action_config.external_run_id_selector.resolve(payload)
        )
    async with ImbiClient() as client:
        response = await client.record_deployment(
            ctx.org_slug,
            ctx.project_id,
            version_value,
            environment,
            event_body,
        )
    if response.status_code == http.HTTPStatus.NOT_FOUND:
        LOGGER.warning(
            'Release %r missing for project %s; status %r dropped',
            version_value,
            ctx.project_id,
            status,
        )

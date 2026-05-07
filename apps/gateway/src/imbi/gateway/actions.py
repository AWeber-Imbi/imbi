import http
import logging
import typing

import httpx
import jsonpointer
import pydantic
import pydantic_core
import pydantic_settings
from pydantic import json_schema
from pydantic_core import core_schema

from imbi_gateway import helpers, version

if typing.TYPE_CHECKING:
    from collections import abc


class ActionSettings(pydantic_settings.BaseSettings):
    model_config = {'env_prefix': 'ACTIONS_'}
    imbi_url: pydantic.HttpUrl = pydantic.HttpUrl('http://imbi-api:8000')
    imbi_token: str


LOGGER = logging.getLogger(__name__)


class _JsonPointerImplementation:
    @classmethod
    def __get_pydantic_core_schema__(
        cls,
        _source_type: typing.Any,  # noqa: ANN401
        _handler: pydantic.GetCoreSchemaHandler,
    ) -> pydantic_core.CoreSchema:
        return core_schema.no_info_plain_validator_function(
            cls._validate, serialization=core_schema.to_string_ser_schema()
        )

    @classmethod
    def __get_pydantic_json_schema__(
        cls,
        _schema: pydantic_core.CoreSchema,
        _handler: pydantic.GetJsonSchemaHandler,
    ) -> json_schema.JsonSchemaValue:
        return {'type': 'string', 'format': 'json-pointer'}

    @staticmethod
    def _validate(value: object) -> jsonpointer.JsonPointer:
        if isinstance(value, jsonpointer.JsonPointer):
            return value
        if isinstance(value, str):
            try:
                return jsonpointer.JsonPointer(value)
            except jsonpointer.JsonPointerException as e:
                raise ValueError(str(e)) from e
        raise ValueError(
            f'Expected a string or JsonPointer, got {type(value)}'
        )


JsonPointer = typing.Annotated[
    jsonpointer.JsonPointer, _JsonPointerImplementation
]


class UpdateProjectRule(pydantic.BaseModel):
    path: JsonPointer
    from_: typing.Annotated[JsonPointer, pydantic.Field(alias='from')]


UpdateProjectRules = pydantic.TypeAdapter(list[UpdateProjectRule])


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


class _DeploymentCreator(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='ignore')
    id: int


class _Deployment(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='ignore')
    ref: str
    url: pydantic.HttpUrl
    environment: str
    creator: _DeploymentCreator | None = None


class _DeploymentEvent(pydantic.BaseModel):
    """Subset of the GitHub ``deployment`` webhook payload."""

    model_config = pydantic.ConfigDict(extra='ignore')
    deployment: _Deployment


class _DeploymentStatus(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(extra='ignore')
    state: str


class _DeploymentStatusEvent(pydantic.BaseModel):
    """Subset of the GitHub ``deployment_status`` webhook payload."""

    model_config = pydantic.ConfigDict(extra='ignore')
    deployment: _Deployment
    deployment_status: _DeploymentStatus


# GitHub deployment_status.state -> Imbi _DEPLOYMENT_STATUS literal.
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


async def update_project(
    org_slug: str,
    project_id: str,
    body: object,
    user_id: str | None,
    update_spec: str,
) -> None:
    del user_id  # unused — patch attribution is the gateway's service token
    updates = UpdateProjectRules.validate_json(update_spec)
    LOGGER.info('Updating project /%s/%s', org_slug, project_id)
    LOGGER.info('%r', updates)
    patch = [
        {
            'op': 'replace',
            'path': str(update.path),
            'value': update.from_.resolve(body),
        }
        for update in updates
    ]
    async with ImbiClient() as client:
        await client.patch_project(org_slug, project_id, patch)


async def create_release(
    org_slug: str,
    project_id: str,
    body: object,
    user_id: str | None,
    handler_config: str,
) -> None:
    """Processes a deployment notification and ensures the release exists.

    https://docs.github.com/en/enterprise-cloud@latest/webhooks/webhook-events-and-payloads#deployment

    The release version is taken from ``/deployment/ref`` and a link to
    the GitHub deployment URL is attached. ``user_id`` (the resolved
    Imbi user's email) is passed as ``created_by`` when present;
    otherwise the API defaults to the gateway's service principal.
    """
    del handler_config  # not used by this handler today
    payload = _DeploymentEvent.model_validate(body)
    create_body: dict[str, object] = {
        'version': payload.deployment.ref,
        'title': payload.deployment.ref,
        'links': [
            {
                'type': 'github_deployment',
                'url': str(payload.deployment.url),
                'label': 'GitHub Deployment',
            }
        ],
    }
    if user_id is not None:
        create_body['created_by'] = user_id
    async with ImbiClient() as client:
        response = await client.create_release(
            org_slug, project_id, create_body
        )
    if response.status_code == http.HTTPStatus.CONFLICT:
        LOGGER.debug(
            'Release %r already exists for project %s',
            payload.deployment.ref,
            project_id,
        )


async def add_deployment_event(
    org_slug: str,
    project_id: str,
    body: object,
    user_id: str | None,
    handler_config: str,
) -> None:
    """Processes a deployment_status notification.

    https://docs.github.com/en/enterprise-cloud@latest/webhooks/webhook-events-and-payloads#deployment_status

    Appends a deployment event to the release's DEPLOYED_TO edge for
    the matching environment. ``record_deployment`` has no
    ``created_by`` field so ``user_id`` is unused here.
    """
    del user_id, handler_config
    payload = _DeploymentStatusEvent.model_validate(body)
    status = _STATUS_MAP.get(payload.deployment_status.state)
    if status is None:
        LOGGER.warning(
            'Unmapped deployment_status.state %r — skipping',
            payload.deployment_status.state,
        )
        return
    async with ImbiClient() as client:
        response = await client.record_deployment(
            org_slug,
            project_id,
            payload.deployment.ref,
            payload.deployment.environment,
            {'status': status, 'note': str(payload.deployment.url)},
        )
    if response.status_code == http.HTTPStatus.NOT_FOUND:
        LOGGER.warning(
            'Release %r missing for project %s; status %r dropped',
            payload.deployment.ref,
            project_id,
            status,
        )

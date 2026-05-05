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
            LOGGER.warning(
                'Failed to patch project %r: %r', url, response.json()
            )
        return response


async def update_project(
    org_slug: str, project_id: str, body: object, update_spec: str
) -> None:
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
    LOGGER.info('patch: %r', patch)
    async with ImbiClient() as client:
        await client.patch_project(org_slug, project_id, patch)

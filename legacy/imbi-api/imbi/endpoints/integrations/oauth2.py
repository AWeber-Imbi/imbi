from __future__ import annotations

import http
import typing

import jsonpatch
import pydantic

from imbi import errors, postgres
from imbi.endpoints import base


class OAuth2CreationRequest(pydantic.BaseModel):
    authorization_endpoint: pydantic.HttpUrl
    token_endpoint: pydantic.HttpUrl
    revoke_endpoint: typing.Union[pydantic.HttpUrl, None]
    callback_url: typing.Union[pydantic.HttpUrl, None]
    client_id: str
    client_secret: typing.Union[str, None]
    use_pkce: bool


class OAuth2Details(pydantic.BaseModel):
    authorization_endpoint: pydantic.HttpUrl
    token_endpoint: pydantic.HttpUrl
    revoke_endpoint: typing.Union[pydantic.HttpUrl, None] = None
    callback_url: typing.Union[pydantic.HttpUrl, None]
    client_id: str
    client_secret: typing.Union[str, None]
    use_pkce: bool

    @pydantic.field_serializer('client_secret')
    def hide_secret(self, v) -> str:
        return None if v is None else '********'


class RecordRequestHandler(base.PydanticHandlerMixin,
                           base.AuthenticatedRequestHandler):
    NAME = 'oauth2-management'

    async def _get_oauth2_details(
            self, integration_name: str) -> OAuth2Details | None:
        result = await self.postgres_execute(
            'SELECT authorization_endpoint, token_endpoint, revoke_endpoint,'
            '       callback_url, client_id, client_secret,'
            '       public_client AS use_pkce'
            '  FROM v1.oauth2_integrations'
            ' WHERE name = %(integration_name)s',
            {'integration_name': integration_name})
        return None if not result else OAuth2Details.model_validate(result.row)

    @base.require_permission('admin')
    async def get(self, integration_name: str) -> None:
        details = await self._get_oauth2_details(integration_name)
        if not details:
            raise errors.ItemNotFound(
                'Integration %r does not support OAuth2 connections',
                integration_name)
        self.send_response(details)

    @base.require_permission('admin')
    async def post(self, integration_name: str) -> None:
        request = self.parse_request_body_as(OAuth2CreationRequest)

        if await self._get_oauth2_details(integration_name):
            raise errors.ApplicationError(
                http.HTTPStatus.CONFLICT,
                'Integration %r already has OAuth2 connection details',
                integration_name)

        client_secret = None
        if request.client_secret:
            client_secret = request.client_secret

        await self.postgres_execute(
            'INSERT INTO v1.oauth2_integrations ('
            '            name, api_endpoint, callback_url,'
            '            authorization_endpoint, token_endpoint,'
            '            revoke_endpoint, client_id, client_secret,'
            '            public_client)'
            '     SELECT i.name, i.api_endpoint, %(callback_url)s,'
            '            %(authorization_endpoint)s, %(token_endpoint)s,'
            '            %(revoke_endpoint)s, %(client_id)s,'
            '            %(client_secret)s, %(public_client)s'
            '       FROM v1.integrations AS i'
            '      WHERE i.name = %(integration_name)s', {
                'integration_name': integration_name,
                'callback_url': (str(request.callback_url)
                                 if request.callback_url else None),
                'authorization_endpoint': str(request.authorization_endpoint),
                'token_endpoint': str(request.token_endpoint),
                'revoke_endpoint': (str(request.revoke_endpoint)
                                    if request.revoke_endpoint else None),
                'client_id': request.client_id,
                'client_secret': client_secret,
                'public_client': request.use_pkce,
            })
        self.send_response(
            OAuth2Details.model_validate({
                'authorization_endpoint': request.authorization_endpoint,
                'token_endpoint': request.token_endpoint,
                'revoke_endpoint': request.revoke_endpoint,
                'callback_url': request.callback_url,
                'client_id': request.client_id,
                'client_secret': request.client_secret,
                'use_pkce': request.use_pkce,
            }))

    @base.require_permission('admin')
    async def delete(self, integration_name: str) -> None:
        result = await self.postgres_execute(
            'DELETE FROM v1.oauth2_integrations'
            '      WHERE name = %(integration_name)s',
            {'integration_name': integration_name},
            metric_name='delete-oauth2-details')
        if not result:
            raise errors.ItemNotFound(
                'Integration %r does not support OAuth2 connections',
                integration_name)
        self.set_status(http.HTTPStatus.NO_CONTENT, reason='Item Deleted')

    @base.require_permission('admin')
    async def patch(self, integration_name: str) -> None:
        try:
            patch = jsonpatch.JsonPatch(self.get_request_body())
        except (jsonpatch.JsonPatchException,
                jsonpatch.JsonPointerException) as error:
            raise errors.ApplicationError(http.HTTPStatus.UNPROCESSABLE_ENTITY,
                                          'bad-patch',
                                          'Failed to deserialize patch: %s',
                                          error)

        details = await self._get_oauth2_details(integration_name)
        if not details:
            raise errors.ItemNotFound(
                'Integration %r does not support OAuth2 connections',
                integration_name)

        original = details.model_dump(mode='json')
        if original['client_secret']:  # enable `test` on real client secret
            original['client_secret'] = details.client_secret
        # limit operations to protect secret
        patch.operations = {
            name: operation
            for name, operation in patch.operations.items()
            if name not in {'copy', 'move'}
        }

        updated = patch.apply(original)
        try:
            OAuth2Details.model_validate(updated)
        except pydantic.ValidationError as error:
            raise errors.PydanticValidationError(
                error, 'Failed to validate new OAuth2 details') from None

        changed = {
            column
            for column in OAuth2Details.model_fields.keys()
            if updated[column] != original[column]
        }
        if not changed:
            self.set_status(http.HTTPStatus.NOT_MODIFIED)
            return

        if updated['client_secret']:
            updated['client_secret'] = updated['client_secret']
        async with self.application.postgres_connector(
                self.on_postgres_error, self.on_postgres_timing) as conn:
            # handle mismatch between representation and DB
            original['public_client'] = original.pop('use_pkce')
            updated['public_client'] = updated.pop('use_pkce')
            if 'use_pkce' in changed:
                changed.remove('use_pkce')
                changed.add('public_client')

            await postgres.update_entity(conn,
                                         'v1',
                                         'oauth2_integrations',
                                         original,
                                         updated,
                                         changed,
                                         id_column='name',
                                         id_value=integration_name)

        self.send_response(await self._get_oauth2_details(integration_name))

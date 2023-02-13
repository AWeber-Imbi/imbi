import logging
import os
import re
import urllib.parse

import aioredis
import google.auth.exceptions
import sprockets.mixins.http
import yarl
from google.auth.transport import requests
from google.oauth2 import id_token

import imbi.user
from imbi import errors, oauth2
from imbi.endpoints import base

LOGGER = logging.getLogger(__name__)


class RedirectHandler(sprockets.mixins.http.HTTPClientMixin,
                      base.RequestHandler):
    integration: oauth2.OAuth2Integration

    NAME = 'google-redirect'

    ADD_TOKEN_SQL = re.sub(r'\s+', ' ', """
        INSERT INTO v1.user_oauth2_tokens
                    (username, integration, external_id,
                     access_token, refresh_token)
             VALUES (%(username)s, %(integration)s, %(external_id)s,
                     %(access_token)s, %(refresh_token)s)
        ON CONFLICT (integration, external_id)
                 DO UPDATE SET access_token = EXCLUDED.access_token,
                              refresh_token = EXCLUDED.refresh_token
    """)

    UPDATE_TOKEN_SQL = re.sub(r'\s+', ' ', """
       UPDATE v1.user_oauth2_tokens
          SET access_token = %(access_token)s,
              username = %(username)s
        WHERE integration = %(integration)s
          AND external_id = %(external_id)s
    """)

    @property
    def _redis(self) -> aioredis.Redis:
        return self.application.session_redis

    async def prepare(self) -> None:
        await super().prepare()
        if not self._finished:
            self.integration = await oauth2.OAuth2Integration.by_name(
                self.application, self.integration_name)
            if not self.integration:
                raise errors.IntegrationNotFound(self.integration_name)

    async def get(self):
        state = self.get_query_argument('state', default=None)
        if not state:
            raise errors.BadRequest('No state in request payload')
        redis_state = await self._redis.get(state)
        if not redis_state:
            raise errors.Forbidden('Returned state CRSF token not found')
        await self._redis.delete(state)

        code = self.get_query_argument('code', default=None)
        if not code:
            raise errors.BadRequest('No code in request payload')

        (openid_token, access_token,
         refresh_token) = await self.exchange_code_for_tokens(code)

        user = await self.sync_user(openid_token)
        await self.save_session(user)
        await self.upsert_token(user.username, user.external_id, access_token,
                                refresh_token)

        target = yarl.URL(self.request.full_url()).with_path('/ui/')
        self.redirect(str(target))

    async def save_session(self, user):
        self.session.user = user
        await self.session.save()

    async def sync_user(self, openid_token) -> imbi.user.User:
        try:
            id_info = id_token.verify_oauth2_token(
                openid_token, requests.Request(), self.integration.client_id)
        except google.auth.exceptions.GoogleAuthError as e:
            raise errors.BadRequest('Token issuer is invalid: %s', e)
        except ValueError:
            raise errors.BadRequest('Invalid token')
        if id_info['aud'] != self.integration.client_id:
            raise errors.BadRequest('Invalid token: client ID does not match')
        if id_info['hd'] not in self.settings['google']['valid_domains']:
            raise errors.Forbidden('Invalid Google domain sign in')
        user_id = id_info['sub']
        user_email = id_info['email']
        display_name = id_info['name']
        username = user_email.split('@')[0]
        imbi_user = imbi.user.User(self.application, username=username,
                                   google_user=True, external_id=user_id,
                                   display_name=display_name,
                                   email_address=user_email)
        await imbi_user.refresh()
        return imbi_user

    async def exchange_code_for_tokens(self, code):
        body = urllib.parse.urlencode({
            'client_id': self.integration.client_id,
            'client_secret': self.integration.client_secret,
            'grant_type': 'authorization_code',
            'redirect_uri': self.integration.callback_url,
            'code': code,
        })
        response = await self.http_fetch(
            str(self.integration.token_endpoint),
            method='POST',
            body=body,
            content_type='application/x-www-form-urlencoded'
        )
        if not response.ok:
            self.logger.error('failed to exchange auth code for token: %s %s',
                              response.body['error'],
                              response.body['error_description'])
            raise errors.InternalServerError(
                'failed exchange auth code for token: %s',
                response.code,
                title='Google authorization failure',
                instance={
                    'error': response.body['error'],
                    'error_description': response.body['error_description'],
                })
        return (
            response.body.get('id_token'),
            response.body.get('access_token'),
            response.body.get('refresh_token')
        )

    async def upsert_token(self, username, external_id, access_token,
                           refresh_token):
        if refresh_token:
            await self.postgres_execute(self.ADD_TOKEN_SQL, {
                'username': username,
                'external_id': external_id,
                'access_token': access_token,
                'refresh_token': refresh_token,
                'integration': self.integration_name
            })
        else:
            await self.postgres_execute(self.UPDATE_TOKEN_SQL, {
                'username': username,
                'external_id': external_id,
                'access_token': access_token,
                'integration': self.integration_name
            })

    @property
    def integration_name(self):
        env = os.environ.get('ENVIRONMENT', 'production').lower()
        return f'google-{env}'

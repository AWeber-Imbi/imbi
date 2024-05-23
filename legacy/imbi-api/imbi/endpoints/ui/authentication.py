import uuid

import aioredis
import yarl

from imbi import errors, oauth2
from imbi.endpoints import base


class LoginRequestHandler(base.RequestHandler):

    NAME = 'ui-login'

    async def post(self, *args, **kwargs):
        body = self.get_request_body()
        if not await self.session.authenticate(body.get('username'),
                                               body.get('password')):
            self.logger.debug('Session failed to authenticate')
            self.set_status(401)
            self.send_response({'message': 'Authentication Failure'})
            return
        await self.session.save()
        self.set_status(200)
        self.send_response(self.session.user.as_dict())


class GoogleLoginRequestHandler(base.RequestHandler):
    integration: oauth2.OAuth2Integration

    NAME = 'ui-login-google'

    async def prepare(self) -> None:
        await super().prepare()
        if not self._finished:
            self.integration = await oauth2.OAuth2Integration.by_name(
                self.application, self.integration_name)
            if not self.integration:
                raise errors.IntegrationNotFound(self.integration_name)

    async def get(self, *args, **kwargs):
        state = str(uuid.uuid4())
        await self._redis.set(state, 'google-login-crsf', expire=86400)
        target = yarl.URL(self.integration.authorization_endpoint).with_query({
            'client_id': str(self.integration.client_id),
            'redirect_uri': str(self.integration.callback_url),
            'state': state,
            'response_type': 'code',
            'scope': ' '.join([
                'openid', 'https://www.googleapis.com/auth/userinfo.email',
                'https://www.googleapis.com/auth/userinfo.profile'
            ]),
            'access_type': 'offline',
            'include_granted_scopes': 'true',
            'prompt': 'select_account',
        })
        self.redirect(str(target))

    @property
    def _redis(self) -> aioredis.Redis:
        return self.application.session_redis

    @property
    def integration_name(self):
        return self.settings['google']['integration_name']


class LogoutRequestHandler(base.RequestHandler):

    NAME = 'ui-logout'

    async def get(self, *args, **kwargs):
        await self.session.clear()
        self.send_response({'loggedOut': True})


class ConnectionRequestHandler(base.AuthenticatedRequestHandler):
    async def delete(self, integration_name: str) -> None:
        await self.postgres_execute(
            'DELETE FROM v1.user_oauth2_tokens'
            ' WHERE integration = %(integration_name)s'
            '   AND username = %(username)s', {
                'integration_name': integration_name,
                'username': self._current_user.username,
            })
        self.set_status(204)

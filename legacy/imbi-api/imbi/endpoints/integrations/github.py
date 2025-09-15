import base64
import dataclasses
import typing

import sprockets.mixins.http
import yarl

from imbi import errors, oauth2, user
from imbi.endpoints import base


@dataclasses.dataclass
class GitHubToken:
    access_token: str
    refresh_token: str


class RedirectHandler(sprockets.mixins.http.HTTPClientMixin,
                      base.RequestHandler):
    integration: 'oauth2.OAuth2Integration'

    NAME = 'github-redirect'

    async def prepare(self) -> None:
        await super().prepare()
        if not self._finished:
            self.integration = await oauth2.OAuth2Integration.by_name(
                self.application, 'github')
            if not self.integration:
                raise errors.IntegrationNotFound('github')

    async def get(self):
        auth_code = self.get_query_argument('code')
        state = base64.b64decode(self.get_query_argument('state'),
                                 b'-_').decode('utf-8')
        username, target = state.rstrip('?').split(':')
        token = await self.exchange_code_for_token(auth_code)
        try:
            user_id, email = await self.fetch_github_user(token)
            imbi_user = user.User(self.application, username=username)
            await imbi_user.refresh()
            if imbi_user.email_address != email:
                raise errors.Forbidden(
                    'mismatched user email: expected %r received %r',
                    imbi_user.email_address,
                    email,
                    title='GitHub authorization failure',
                    detail='unexpected email address {} for user {}'.format(
                        email, imbi_user.username))
            await self.integration.upsert_user_tokens(imbi_user.username,
                                                      str(user_id),
                                                      token.access_token,
                                                      token.refresh_token)
            await imbi_user.update_last_seen_at()
        except Exception:
            await self.revoke_github_token(token, username)
            raise

        target = yarl.URL(self.request.full_url()).with_path(target or '/ui/')
        self.redirect(str(target))

    async def exchange_code_for_token(self, code) -> GitHubToken:
        body = {
            'client_id': self.integration.client_id,
            'client_secret': self.integration.client_secret,
            'grant_type': 'authorization_code',
            'redirect_uri': str(self.integration.callback_url),
            'code': code,
        }
        response = await self.http_fetch(
            str(self.integration.token_endpoint),
            method='POST',
            body=body,
            content_type=sprockets.mixins.http.CONTENT_TYPE_JSON,
            request_headers={
                'X-GitHub-Api-Version': '2022-11-28',
                'Accept': sprockets.mixins.http.CONTENT_TYPE_JSON
            })
        if not response.ok:
            self.logger.error('failed to exchange auth code for token: %s %s',
                              response.body['error'],
                              response.body['error_description'])
            raise errors.InternalServerError(
                'failed exchange auth code for token: %s',
                response.code,
                title='GitHub authorization failure',
                instance={
                    'error': response.body['error'],
                    'error_description': response.body['error_description'],
                })
        self.logger.debug('response_body %r', response.body)
        return GitHubToken(access_token=response.body['access_token'],
                           refresh_token=response.body['refresh_token'])

    async def fetch_github_user(self, token: GitHubToken) \
            -> typing.Tuple[int, str]:
        response = await self.http_fetch(
            str(self.integration.api_endpoint / 'user'),
            request_headers={
                'X-GitHub-Api-Version': '2022-11-28',
                'Accept': sprockets.mixins.http.CONTENT_TYPE_JSON,
                'Authorization': f'Bearer {token.access_token}'
            })
        if response.ok:
            return (response.body['id'], response.body['email'])
        raise errors.InternalServerError(
            'failed to retrieve GitHub user from access token',
            title='GitHub user lookup failure')

    async def revoke_github_token(self, token: GitHubToken, username: str):
        credentials = []
        token_types = []
        if token.access_token:
            credentials.append(token.access_token)
            token_types.append('access_token')
        if token.refresh_token:
            credentials.append(token.refresh_token)
            token_types.append('refresh_token')

        if not credentials:
            return

        body = {'credentials': credentials}
        response = await self.http_fetch(
            str(self.integration.api_endpoint / 'credentials' / 'revoke'),
            method='POST',
            body=body,
            content_type=sprockets.mixins.http.CONTENT_TYPE_JSON,
            request_headers={
                'X-GitHub-Api-Version': '2022-11-28',
                'Accept': sprockets.mixins.http.CONTENT_TYPE_JSON,
            },
        )

        if not response.ok:
            self.logger.warning(
                'failed to revoke GitHub credentials for user %s: %s '
                '(tokens: %s)', username, response.code,
                ', '.join(token_types))

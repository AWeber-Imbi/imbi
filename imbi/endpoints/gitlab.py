import dataclasses
import typing
import urllib.parse

import problemdetails
import sprockets.mixins.http
import yarl

from . import base
from .. import integrations, user


@dataclasses.dataclass
class GitlabToken:
    access_token: str
    refresh_token: str


class RedirectHandler(sprockets.mixins.http.HTTPClientMixin,
                      base.RequestHandler):
    integration: integrations.OAuth2Integration

    async def prepare(self) -> None:
        await super().prepare()
        if not self._finished:
            self.integration = await integrations.OAuth2Integration.by_name(
                self.application, 'gitlab')
            if not self.integration:
                raise problemdetails.Problem(
                    500, 'application lookup failed for %s', 'gitlab',
                    type='https://imbi.aweber.com/errors/#server-error',
                    title='Internal server error')

    async def get(self):
        auth_code = self.get_query_argument('code')
        state = self.get_query_argument('state')
        token = await self.exchange_code_for_token(auth_code)
        try:
            user_id, user_name, email = await self.fetch_gitlab_user(token)
            imbi_user = user.User(self.application, username=state)
            await imbi_user.refresh()
            if imbi_user.email_address != email:
                raise problemdetails.Problem(
                    403, 'mismatched user email: expected %r received %r',
                    imbi_user.email_address, email,
                    type='https://imbi.aweber.com/errors/#gitlab-auth-failure',
                    title='Gitlab authorization failure',
                    detail='unexpected email address {} for user {}'.format(
                        email, imbi_user.username),
                )
            await self.integration.add_user_token(
                imbi_user, str(user_id), token.access_token,
                token.refresh_token)
        except Exception:
            await self.revoke_gitlab_token(token)
            raise

        target = yarl.URL(self.request.full_url())
        target = target.with_path('/ui/user/profile')
        self.redirect(str(target))

    async def exchange_code_for_token(self, code) -> GitlabToken:
        body = urllib.parse.urlencode({
            'client_id': self.integration.client_id,
            'client_secret': self.integration.client_secret,
            'grant_type': 'authorization_code',
            'redirect_uri': str(self.integration.callback_url),
            'code': code,
        })
        response = await self.http_fetch(
            str(self.integration.token_endpoint), method='POST', body=body,
            content_type='application/x-www-form-urlencoded')
        if not response.ok:
            self.logger.error('failed to exchange auth code for token: %s %s',
                              response.body['error'],
                              response.body['error_description'])
            raise problemdetails.Problem(
                500, 'failed exchange auth code for token: %s', response.code,
                type='https://imbi.aweber.com/errors/#gitlab-auth-failure',
                title='Gitlab authorization failure',
                instance={
                    'error': response.body['error'],
                    'error_description': response.body['error_description'],
                })
        self.logger.debug('response_body %r', response.body)
        return GitlabToken(access_token=response.body['access_token'],
                           refresh_token=response.body['refresh_token'])

    async def fetch_gitlab_user(self, token: GitlabToken) -> typing.Tuple[
            int, str, str]:
        response = await self.http_fetch(
            str(self.integration.api_endpoint / 'user'),
            request_headers={'Accept': 'application/json',
                             'Authorization': f'Bearer {token.access_token}'})
        if response.ok:
            return (response.body['id'], response.body['username'],
                    response.body['email'])
        raise problemdetails.Problem(
            500, 'failed to retrieve gitlab user from access token',
            type='https://imbi.aweber.com/errors/#gitlab-auth-failure',
            title='Gitlab user lookup failure')

    async def revoke_gitlab_token(self, token: GitlabToken):
        ...


class UserNamespacesHandler(sprockets.mixins.http.HTTPClientMixin,
                            base.AuthenticatedRequestHandler):
    integration: integrations.OAuth2Integration

    async def prepare(self) -> None:
        await super().prepare()
        if not self._finished:
            self.integration = await integrations.OAuth2Integration.by_name(
                self.application, 'gitlab')
            if not self.integration:
                raise problemdetails.Problem(
                    500, 'application lookup failed for %s', 'gitlab',
                    type='https://imbi.aweber.com/errors/#server-error',
                    title='Internal server error')

    async def get(self):
        namespaces = []
        imbi_user = await self.get_current_user()  # shouldn't be None
        url = self.integration.api_endpoint / 'groups'
        url = url.with_query({'min_access_level': 30})
        for token in await self.integration.get_user_tokens(imbi_user):
            entries = await self.fetch_all_pages(url, token)
            namespaces.extend([
                {
                    'name': entry['full_name'],
                    'id': entry['id'],
                }
                for entry in entries
            ])

        namespaces.sort(key=lambda elm: elm['name'])
        self.send_response(namespaces)

    async def fetch_all_pages(
            self, url: yarl.URL, token: integrations.IntegrationToken
    ) -> typing.Sequence[dict]:
        entries = []
        while url is not None:
            response = await self.http_fetch(
                str(url),
                request_headers={
                    'Accept': 'application/json',
                    'Authorization': f'Bearer {token.access_token}',
                }
            )
            if response.ok:
                entries.extend(response.body)
            else:  # TODO -- handle token expiration
                raise problemdetails.Problem(
                    500, 'failed to retrieve groups: %s', response.code,
                    type='https://imbi.aweber.com/errors/#server-error',
                    title='Internal server error')

            url = None
            for link in response.links:
                if link['rel'] == 'next':
                    url = yarl.URL(link['target'])
                    break

        return entries


class ProjectsHandler(sprockets.mixins.http.HTTPClientMixin,
                      base.AuthenticatedRequestHandler):
    integration: integrations.OAuth2Integration

    async def prepare(self) -> None:
        await super().prepare()
        if not self._finished:
            self.integration = await integrations.OAuth2Integration.by_name(
                self.application, 'gitlab')
            if not self.integration:
                raise problemdetails.Problem(
                    500, 'application lookup failed for %s', 'gitlab',
                    type='https://imbi.aweber.com/errors/#server-error',
                    title='Internal server error')

    async def get(self):
        group_arg = self.get_query_argument('group_id')
        try:
            group_id = int(group_arg)
        except ValueError:
            raise problemdetails.Problem(
                400, 'invalid group ID: %r', group_arg,
                type='https://imbi.aweber.com/errors/#invalid-parameter',
                title='Invalid Query Parameter')

        imbi_user = await self.get_current_user()
        url = (self.integration.api_endpoint / 'groups' / str(group_id)
               / 'projects')
        url = url.with_query({
            'include_subgroups': 'false',
            'simple': 'true',
            'with_shared': 'false',
        })

        projects = []
        for token in await self.integration.get_user_tokens(imbi_user):
            entries = await self.fetch_all_pages(url, token)
            projects.extend([
                {
                    'name': entry['name'],
                    'id': entry['id'],
                    'web_url': entry['web_url'],
                }
                for entry in entries
            ])

        self.send_response(projects)

    async def fetch_all_pages(
            self, url: yarl.URL, token: integrations.IntegrationToken
    ) -> typing.Sequence[dict]:
        entries = []
        while url is not None:
            response = await self.http_fetch(
                str(url),
                request_headers={
                    'Accept': 'application/json',
                    'Authorization': f'Bearer {token.access_token}',
                }
            )
            if response.ok:
                entries.extend(response.body)
            else:  # TODO -- handle token expiration
                raise problemdetails.Problem(
                    500, 'failed to retrieve groups: %s', response.code,
                    type='https://imbi.aweber.com/errors/#server-error',
                    title='Internal server error')

            url = None
            for link in response.links:
                if link['rel'] == 'next':
                    url = yarl.URL(link['target'])
                    break

        return entries

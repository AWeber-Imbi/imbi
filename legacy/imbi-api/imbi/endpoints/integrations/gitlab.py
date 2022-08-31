import base64
import dataclasses
import typing
import urllib.parse

import sprockets.mixins.http
import yarl

from imbi import errors, oauth2, user
from imbi.clients import gitlab
from imbi.endpoints import base


@dataclasses.dataclass
class GitlabToken:
    access_token: str
    refresh_token: str


class RedirectHandler(sprockets.mixins.http.HTTPClientMixin,
                      base.RequestHandler):
    integration: 'oauth2.OAuth2Integration'

    NAME = 'gitlab-redirect'

    async def prepare(self) -> None:
        await super().prepare()
        if not self._finished:
            self.integration = await oauth2.OAuth2Integration.by_name(
                self.application, 'gitlab')
            if not self.integration:
                raise errors.IntegrationNotFound('gitlab')

    async def get(self):
        auth_code = self.get_query_argument('code')
        state = base64.b64decode(
            self.get_query_argument('state'), b'-_').decode('utf-8')
        username, target = state.rstrip('?').split(':')
        token = await self.exchange_code_for_token(auth_code)
        try:
            user_id, user_name, email = await self.fetch_gitlab_user(token)
            imbi_user = user.User(self.application, username=username)
            await imbi_user.refresh()
            if imbi_user.email_address != email:
                raise errors.Forbidden(
                    'mismatched user email: expected %r received %r',
                    imbi_user.email_address, email,
                    title='Gitlab authorization failure',
                    detail='unexpected email address {} for user {}'.format(
                        email, imbi_user.username))
            await self.integration.add_user_token(
                imbi_user, str(user_id), token.access_token,
                token.refresh_token)

        # Revoke the gitlab token if we cannot use or save it.  This
        # is a catch-all case since GitLab does not remove tokens based
        # on a lifetime.
        except Exception:
            await self.revoke_gitlab_token(token)
            raise

        target = yarl.URL(self.request.full_url()).with_path(target or '/ui/')
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
            raise errors.InternalServerError(
                'failed exchange auth code for token: %s', response.code,
                title='GitLab authorization failure',
                instance={
                    'error': response.body['error'],
                    'error_description': response.body['error_description'],
                })
        self.logger.debug('response_body %r', response.body)
        return GitlabToken(access_token=response.body['access_token'],
                           refresh_token=response.body['refresh_token'])

    async def fetch_gitlab_user(self, token: GitlabToken) \
            -> typing.Tuple[int, str, str]:
        response = await self.http_fetch(
            str(self.integration.api_endpoint / 'user'),
            request_headers={'Accept': 'application/json',
                             'Authorization': f'Bearer {token.access_token}'})
        if response.ok:
            return (response.body['id'], response.body['username'],
                    response.body['email'])
        raise errors.InternalServerError(
            'failed to retrieve GitLab user from access token',
            title='GitLab user lookup failure')

    async def revoke_gitlab_token(self, token: GitlabToken):
        ...


class GitLabIntegratedHandler(base.AuthenticatedRequestHandler):

    NAME = 'gitlab-integrated'
    client: gitlab.GitLabClient

    async def prepare(self) -> None:
        await super().prepare()
        if not self._finished:
            integration = await oauth2.OAuth2Integration.by_name(
                self.application, 'gitlab')
            if not integration:
                raise errors.IntegrationNotFound('gitlab')

            imbi_user = await self.get_current_user()  # never None
            tokens = await integration.get_user_tokens(imbi_user)
            if not tokens:
                raise errors.Forbidden('no GitLab tokens for %r', imbi_user,
                                       title='GitLab Not Connected')
            self.client = gitlab.GitLabClient(tokens[0], self.application)


class UserNamespacesHandler(GitLabIntegratedHandler):

    NAME = 'gitlab-user-namespace'

    async def get(self):
        entries = await self.client.fetch_all_pages(
            'groups', min_access_level=30)
        namespaces = [{'name': entry['full_name'], 'id': entry['id']}
                      for entry in entries]
        namespaces.sort(key=lambda elm: elm['name'])
        self.send_response(namespaces)


class ProjectsHandler(GitLabIntegratedHandler):

    NAME = 'gitlab-projects'

    async def get(self):
        group_arg = self.get_query_argument('group_id')
        try:
            group_id = int(group_arg)
        except ValueError:
            raise errors.BadRequest('invalid group ID: %r', group_arg,
                                    title='Invalid Query Parameter')

        projects = await self.client.fetch_all_pages(
            'groups', group_id, 'projects', include_subgroups='false',
            simple='true', with_shared='false')
        self.send_response([
            {
                'description': project['description'],
                'name': project['name'],
                'id': project['id'],
                'web_url': project['web_url'],
            }
            for project in projects
        ])

import dataclasses
import logging
import typing
import urllib.parse

import sprockets.mixins.http
import yarl

from . import base
from .. import errors, integrations, user, version


@dataclasses.dataclass
class GitlabToken:
    access_token: str
    refresh_token: str


PROJECT_DEFAULTS = {
    'default_branch': 'main',
    'issues_access_level': 'disabled',
    'issues_enabled': False,  # deprecated but required to disable :(
    'builds_access_level': 'enabled',
    'merge_requests_access_level': 'enabled',
    'operations_access_level': 'disabled',
    'packages_enabled': False,
    'pages_access_level': 'disabled',
    'snippets_access_level': 'enabled',
    'wiki_access_level': 'disabled',
    'wiki_enabled': False,  # deprecated but required to disable :(
}


class GitLabClient(sprockets.mixins.http.HTTPClientMixin):
    def __init__(self, token: 'integrations.IntegrationToken'):
        super().__init__()
        self.logger = logging.getLogger(__package__).getChild('GitLabClient')
        self.token = token
        self.headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.token.access_token}',
        }

    async def api(self, url: typing.Union[yarl.URL, str], *,
                  method: str = 'GET', **kwargs):
        if not isinstance(url, yarl.URL):
            url = yarl.URL(url)
        if not url.is_absolute():
            url = self.token.integration.api_endpoint / url.path.lstrip('/')
        request_headers = kwargs.setdefault('request_headers', {})
        request_headers.update(self.headers)
        if kwargs.get('body', None) is not None:
            request_headers['Content-Type'] = 'application/json'
            kwargs['content_type'] = 'application/json'
        kwargs['user_agent'] = f'imbi/{version} (GitLabClient)'
        self.logger.debug('%s %s %r', method, url, kwargs)
        return await super().http_fetch(str(url), method=method, **kwargs)

    async def fetch_all_pages(self, *path, **query) -> typing.Sequence[dict]:
        url = self.token.integration.api_endpoint
        for component in path:
            url /= component
        if query:
            url = url.with_query(query)

        entries = []
        while url is not None:
            response = await self.api(url)
            if not response.ok:
                raise errors.InternalServerError(
                    'GET %s failed: %s', url, response.code,
                    title='GitLab API Failure')

            entries.extend(response.body)
            for link in response.links:
                if link['rel'] == 'next':
                    url = yarl.URL(link['target'])
                    break
            else:
                url = None

        return entries

    async def fetch_group(self, *group_path) -> typing.Union[dict, None]:
        slug = urllib.parse.quote('/'.join(group_path), safe='')
        url = self.token.integration.api_endpoint
        url = url.with_path(url.path.rstrip('/') + '/groups/' + slug,
                            encoded=True)
        response = await self.api(url)
        if response.code == 404:
            return None
        if response.ok:
            return response.body
        raise errors.InternalServerError(
            'failed to fetch group %s: %s', slug, response.code,
            title='GitLab API Failure')

    async def create_project(self, parent, project_name, **attributes) -> dict:
        for name, value in PROJECT_DEFAULTS.items():
            attributes.setdefault(name, value)
        attributes.update({
            'name': project_name,
            'namespace_id':  parent['id'],
        })
        response = await self.api('projects', method='POST', body=attributes)
        if response.ok:
            return response.body
        raise errors.InternalServerError(
            'failed to create project %s: %s', project_name, response.code,
            title='GitLab API Failure')


class RedirectHandler(sprockets.mixins.http.HTTPClientMixin,
                      base.RequestHandler):
    integration: 'integrations.OAuth2Integration'

    async def prepare(self) -> None:
        await super().prepare()
        if not self._finished:
            self.integration = await integrations.OAuth2Integration.by_name(
                self.application, 'gitlab')
            if not self.integration:
                raise errors.IntegrationNotFound('gitlab')

    async def get(self):
        auth_code = self.get_query_argument('code')
        state = self.get_query_argument('state')
        token = await self.exchange_code_for_token(auth_code)
        try:
            user_id, user_name, email = await self.fetch_gitlab_user(token)
            imbi_user = user.User(self.application, username=state)
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

    async def fetch_gitlab_user(self, token: GitlabToken) -> typing.Tuple[
            int, str, str]:
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
    client: GitLabClient

    async def prepare(self) -> None:
        await super().prepare()
        if not self._finished:
            integration = await integrations.OAuth2Integration.by_name(
                self.application, 'gitlab')
            if not integration:
                raise errors.IntegrationNotFound('gitlab')

            imbi_user = await self.get_current_user()  # never None
            tokens = await integration.get_user_tokens(imbi_user)
            if not tokens:
                raise errors.Forbidden('no GitLab tokens for %r', imbi_user,
                                       title='GitLab Not Connected')
            self.client = GitLabClient(tokens[0])


class UserNamespacesHandler(GitLabIntegratedHandler):
    async def get(self):
        entries = await self.client.fetch_all_pages(
            'groups', min_access_level=30)
        namespaces = [{'name': entry['full_name'], 'id': entry['id']}
                      for entry in entries]
        namespaces.sort(key=lambda elm: elm['name'])
        self.send_response(namespaces)


class ProjectsHandler(GitLabIntegratedHandler):
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

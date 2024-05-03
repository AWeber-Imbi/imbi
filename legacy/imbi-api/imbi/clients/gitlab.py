import base64
import http.client
import logging
import pathlib
import stat
import typing
import urllib.parse

import pydantic
import sprockets.mixins.http
import tornado.web
import yarl

from imbi import errors, oauth2, user, version
if typing.TYPE_CHECKING:
    from imbi import app


class Namespace(pydantic.BaseModel):
    id: int


class ProjectLinks(pydantic.BaseModel):
    self: str


class ProjectInfo(pydantic.BaseModel):
    id: int
    default_branch: str
    namespace: Namespace
    name_with_namespace: str
    web_url: str
    links: ProjectLinks = pydantic.Field(..., alias='_links')


PROJECT_DEFAULTS = {
    'auto_devops_enabled': False,
    'default_branch': 'main',
    'builds_access_level': 'enabled',
    'forking_access_level': 'enabled',
    'initialize_with_readme': False,
    'merge_requests_access_level': 'enabled',
    'only_allow_merge_if_pipeline_succeeds': True,
    'operations_access_level': 'disabled',
    'packages_enabled': False,
    'printing_merge_request_link_enabled': True,
    'remove_source_branch_after_merge': True,
    'snippets_access_level': 'enabled',
    'squash_option': 'default_off',
    'visibility': 'public',
}


class GitLabAPIFailure(errors.ApplicationError):
    def __init__(self, response: sprockets.mixins.http.HTTPResponse,
                 log_message: str, *log_args, **kwargs) -> None:
        status_code = response.code
        kwargs.setdefault('title', 'GitLab API Failure')
        kwargs['gitlab_response_body'] = response.body

        # A GitLab "unauthorized" response is not the same as an
        # Imbi "unauthorized". HTTP unauthorized always refers to
        # the user requested resource which is an Imbi resource.
        if status_code == http.HTTPStatus.UNAUTHORIZED:
            status_code = http.HTTPStatus.FORBIDDEN

        super().__init__(status_code, 'gitlab-api-failure', log_message,
                         *log_args, **kwargs)


async def create_client(
    application: 'app.Application',
    integration_name: str,
    current_user: user.User,
) -> '_GitLabClient':
    tokens = await current_user.fetch_integration_tokens(integration_name)
    if not tokens:
        raise errors.ClientUnavailableError(
            integration_name,
            f'no {integration_name!r} token for {current_user.username}')

    return _GitLabClient(current_user, tokens[0], application)


class _GitLabClient(sprockets.mixins.http.HTTPClientMixin):
    """API Client for GitLab.

    This client sends authenticated HTTP requests to the GitLab API.

    """
    def __init__(self, user: user.User, token: oauth2.IntegrationToken,
                 application: tornado.web.Application):
        super().__init__()
        settings = application.settings['automations']['gitlab']
        self.logger = logging.getLogger(__package__).getChild('GitLabClient')
        self.restrict_to_user = settings.get('restrict_to_user', False)
        self.user = user
        self.token = token
        self.headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.token.access_token}',
        }
        self._user_info: typing.Union[dict, None] = None
        self._user_namespace: typing.Union[dict, None] = None

    async def api(self,
                  url: typing.Union[yarl.URL, str],
                  *,
                  method: str = 'GET',
                  **kwargs):
        """Make an authenticated request to the GitLab API."""
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
        self.logger.debug('%s %s', method, url)

        response = await super().http_fetch(str(url), method=method, **kwargs)
        if response.code == 400 and response.body:
            self.logger.warning('%s %s failed: status=%s response=%r', method,
                                url, response.code, response.body)
        if response.code == http.client.UNAUTHORIZED:  # maybe refresh
            if response.body.get('error', '') == 'invalid_token':
                await self._refresh_token()
                request_headers.update(self.headers)
                response = await super().http_fetch(str(url),
                                                    method=method,
                                                    **kwargs)
        return response

    async def fetch_all_pages(self, *path, **query) -> list[dict]:
        url = self.token.integration.api_endpoint
        for component in path:
            url /= str(component)
        if query:
            url = url.with_query(query)

        entries = []
        while url is not None:
            response = await self.api(url)
            if not response.ok:
                raise GitLabAPIFailure(response, 'GET %s failed: %s', url,
                                       response.code)

            entries.extend(response.body)
            for link in response.links:
                if link['rel'] == 'next':
                    url = yarl.URL(link['target'])
                    break
            else:
                url = None
        return entries

    async def fetch_group(self, *group_path) -> typing.Optional[dict]:
        slug = urllib.parse.quote('/'.join(group_path), safe='')
        url = self.token.integration.api_endpoint
        path = f'{url.path.rstrip("/")}/groups/{slug}'
        url = url.with_path(path, encoded=True).with_query(
            {'with_projects': 'false'})
        response = await self.api(url)
        if response.code == 404:
            self.logger.debug('Group not found: %s', url)
            return None
        if response.ok:
            return response.body
        raise GitLabAPIFailure(response, 'failed to fetch group %s: %s', slug,
                               response.code)

    async def fetch_project(self, project_id: int) \
            -> typing.Optional[ProjectInfo]:
        url = (self.token.integration.api_endpoint / 'projects' /
               str(project_id))
        response = await self.api(url)
        if response.code == 404:
            return None
        if response.ok:
            return ProjectInfo.parse_obj(response.body)
        raise GitLabAPIFailure(response, 'failed to fetch project %s: %s',
                               project_id, response.code)

    async def create_project(self, parent, project_name: str,
                             **attributes) -> ProjectInfo:
        if self.restrict_to_user:
            parent = await self.fetch_user_namespace()

        for name, value in PROJECT_DEFAULTS.items():
            attributes.setdefault(name, value)
        attributes.update({
            'name': project_name,
            'namespace_id': parent['id'],
        })
        response = await self.api('projects', method='POST', body=attributes)
        if response.ok:
            return ProjectInfo.parse_obj(response.body)
        raise GitLabAPIFailure(
            response, 'failed to create project %s in namespace %s: %s',
            project_name, parent['id'], response.code)

    async def delete_project(self, project: ProjectInfo) -> None:
        url = yarl.URL('/projects') / str(project.id)
        response = await self.api(url, method='DELETE')
        # intentionally swallow "Not Found" responses
        if not response.ok and response.code not in (http.HTTPStatus.NOT_FOUND,
                                                     http.HTTPStatus.GONE):
            raise GitLabAPIFailure(
                response,
                '%s failed to delete project %s',
                self.user.username,
                project.web_url,
                detail=f'Failed to delete {project.web_url}')

    async def commit_tree(self, project_info: ProjectInfo,
                          project_dir: pathlib.Path, commit_message: str):
        self.logger.info('creating commit for %s', project_info.id)

        files = [path for path in project_dir.glob('**/*') if path.is_file()]
        self.logger.debug('found %d files in %s', len(files), project_dir)

        actions = [{
            'action': 'create',
            'content': base64.b64encode(file.read_bytes()).decode('ascii'),
            'encoding': 'base64',
            'file_path': str(file.relative_to(project_dir)),
        } for file in files]
        actions.extend([{
            'action': 'chmod',
            'execute_filemode': True,
            'file_path': str(file.relative_to(project_dir)),
        } for file in files if file.stat().st_mode & stat.S_IXUSR])
        self.logger.debug('creating commit with %d actions', len(actions))

        project_url = yarl.URL(project_info.links.self)
        response = await self.api(
            project_url / 'repository' / 'commits',
            method='POST',
            body={
                'branch': project_info.default_branch,
                'commit_message': commit_message,
                'actions': actions,
            },
        )
        if response.ok:
            return response.body
        raise GitLabAPIFailure(response, 'failed to commit to %s: %s',
                               project_url, response.code)

    async def fetch_user_information(self):
        if self._user_info:
            return self._user_info
        response = await self.api(self.token.integration.api_endpoint / 'user')
        if response.ok:
            self._user_info = response.body
            return self._user_info
        raise GitLabAPIFailure(
            response, 'failed to retrieve GitLab user information: %s',
            response.code)

    async def fetch_user_namespace(self):
        if self._user_namespace:
            return self._user_namespace
        user_info = await self.fetch_user_information()
        response = await self.api(self.token.integration.api_endpoint /
                                  'namespaces' / user_info['username'])
        if response.ok:
            self._user_namespace = response.body
            return self._user_namespace
        raise GitLabAPIFailure(
            response,
            'failed to retrieve GitLab user namespace for %s: %s',
            user_info['username'],
            response.code,
            detail='failed to retrieve GitLab user namespace')

    async def _refresh_token(self) -> None:
        body = urllib.parse.urlencode({
            'grant_type': 'refresh_token',
            'refresh_token': self.token.refresh_token,
        })
        self.logger.info('refreshing token for %s (%s)', self.user.username,
                         self.token.external_id)
        self.logger.debug('refresh_request: %r', body)
        response = await super().http_fetch(
            str(self.token.integration.token_endpoint),
            method='POST',
            body=body,
            content_type='application/x-www-form-urlencoded',
            auth_username=self.token.integration.client_id,
            auth_password=self.token.integration.client_secret,
        )
        if response.ok:
            self.logger.debug('refresh response: %r', response.body)
            await self.token.integration.upsert_user_tokens(
                self.user.username, self.token.external_id,
                response.body['access_token'], response.body['refresh_token'],
                self.token.id_token)
            self.token.access_token = response.body['access_token']
            self.token.refresh_token = response.body['refresh_token']
            self.headers['Authorization'] = f'Bearer {self.token.access_token}'
        else:
            self.logger.error('failed to refresh token for %s: %r',
                              self.user.username, response.body)
            raise GitLabAPIFailure(response, 'token refresh failed: %s',
                                   response.code)

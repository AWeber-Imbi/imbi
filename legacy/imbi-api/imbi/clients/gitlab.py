import base64
import logging
import pathlib
import stat
import typing
import urllib.parse

import pydantic
import sprockets.mixins.http
import tornado.web
import yarl

from imbi import errors, oauth2, version


class Namespace(pydantic.BaseModel):
    id: int


class ProjectLinks(pydantic.BaseModel):
    self: str


class ProjectInfo(pydantic.BaseModel):
    id: int
    default_branch: str
    namespace: Namespace
    web_url: str
    links: ProjectLinks = pydantic.Field(..., alias='_links')


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
    """API Client for GitLab.

    This client sends authenticated HTTP requests to the GitLab API.

    """
    def __init__(self,
                 token: oauth2.IntegrationToken,
                 application: tornado.web.Application):
        super().__init__()
        settings = application.settings['automations']['gitlab']
        self.logger = logging.getLogger(__package__).getChild('GitLabClient')
        self.restrict_to_user = settings.get('restrict_to_user', False)
        self.token = token
        self.headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {self.token.access_token}',
        }
        self._user_info: typing.Union[dict, None] = None
        self._user_namespace: typing.Union[dict, None] = None

    async def api(self, url: typing.Union[yarl.URL, str], *,
                  method: str = 'GET', **kwargs):
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
        return await super().http_fetch(str(url), method=method, **kwargs)

    async def fetch_all_pages(self, *path, **query) -> typing.List[dict]:
        url = self.token.integration.api_endpoint
        for component in path:
            url /= str(component)
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

    async def fetch_group(self, *group_path) -> typing.Optional[dict]:
        slug = urllib.parse.quote('/'.join(group_path), safe='')
        url = self.token.integration.api_endpoint
        path = f'{url.path.rstrip("/")}/groups/{slug}'
        url = url.with_path(path, encoded=True)
        response = await self.api(url)
        if response.code == 404:
            self.logger.debug('Group not found: %s', url)
            return None
        if response.ok:
            return response.body
        raise errors.InternalServerError(
            'failed to fetch group %s: %s', slug, response.code,
            title='GitLab API Failure')

    async def fetch_project(self, project_id: int) \
            -> typing.Optional[ProjectInfo]:
        url = (self.token.integration.api_endpoint / 'projects' /
               str(project_id))
        response = await self.api(url)
        if response.code == 404:
            return None
        if response.ok:
            return ProjectInfo.parse_obj(response.body)
        raise errors.InternalServerError(
            'failed to fetch project %s: %s', project_id, response.code,
            title='GitLab API Failure')

    async def create_project(self,
                             parent,
                             project_name: str,
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
        raise errors.InternalServerError(
            'failed to create project %s: %s', project_name, response.code,
            title='GitLab API Failure', gitlab_response=response.body)

    async def commit_tree(self,
                          project_info: ProjectInfo,
                          project_dir: pathlib.Path,
                          commit_message: str):
        self.logger.info('creating commit for %s', project_info.id)

        files = [path for path in project_dir.glob('**/*') if path.is_file()]
        self.logger.debug('found %d files in %s', len(files), project_dir)

        actions = [
            {
                'action': 'create',
                'content': base64.b64encode(file.read_bytes()).decode('ascii'),
                'encoding': 'base64',
                'file_path': str(file.relative_to(project_dir)),
            }
            for file in files
        ]
        actions.extend([
            {
                'action': 'chmod',
                'execute_filemode': True,
                'file_path': str(file.relative_to(project_dir)),
            }
            for file in files
            if file.stat().st_mode & stat.S_IXUSR
        ])
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
        raise errors.InternalServerError(
            'failed to commit to %s: %s', project_url, response.code,
            title='GitLab API Failure', gitlab_response=response.body)

    async def fetch_user_information(self):
        if self._user_info:
            return self._user_info
        response = await self.api(self.token.integration.api_endpoint / 'user')
        if response.ok:
            self._user_info = response.body
            return self._user_info
        raise errors.InternalServerError(
            'failed to retrieve GitLab user information: %s', response.code,
            title='GitLab API Failure')

    async def fetch_user_namespace(self):
        if self._user_namespace:
            return self._user_namespace
        user_info = await self.fetch_user_information()
        response = await self.api(
            self.token.integration.api_endpoint /
            'namespaces' / user_info['username'])
        if response.ok:
            self._user_namespace = response.body
            return self._user_namespace
        raise errors.InternalServerError(
            'failed to retrieve GitLab user namespace for %s: %s',
            user_info['username'], response.code, title='GitLab API Failure')

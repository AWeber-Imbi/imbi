import logging
import typing
import urllib.parse

import sprockets.mixins.http
import tornado.web
import yarl

from imbi import automations, errors, version


def generate_key(project: 'automations.Project') -> str:
    return ':'.join([project.namespace.slug.lower(), project.slug.lower()])


def generate_dashboard_link(project: 'automations.Project',
                            sonar_settings: dict) -> typing.Union[str, None]:
    if sonar_settings['url']:
        root = yarl.URL(sonar_settings['url'])
        return str(root.with_path('/dashboard').with_query({
            'id': generate_key(project),
        }))


class SonarQubeClient(sprockets.mixins.http.HTTPClientMixin):
    enabled: typing.Union[bool, None] = None
    gitlab_alm_key: typing.Union[bool, None, str] = None

    def __init__(self, application: tornado.web.Application, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__package__).getChild(
            'SonarQubeClient')

        settings = application.settings['automations']['sonar']
        try:
            self.admin_token = settings['admin_token']
            self.sonar_url = yarl.URL(settings['url'])
        except KeyError as error:
            if self.__class__.enabled is None:
                self.logger.warning('disabling SonarQube integration due to'
                                    ' missing configuration: %s',
                                    error.args[0])
                self.__class__.enabled = False
            self.api_root = None
            self.admin_token = None
        else:
            self.enabled = True
            self.api_root = self.sonar_url / 'api'

    async def api(self, url: typing.Union[yarl.URL, str], *,
                  method: str = 'GET', **kwargs):
        if not self.enabled:
            raise RuntimeError('SonarQube integration is not enabled')
        if not isinstance(url, yarl.URL):
            url = yarl.URL(url)
        if not url.is_absolute():
            new_url = self.api_root / url.path.lstrip('/')
            url = new_url.with_query(url.query)

        request_headers = kwargs.setdefault('request_headers', {})
        request_headers['Accept'] = 'application/json'
        if kwargs.get('body', None) is not None:
            kwargs['content_type'] = 'application/x-www-form-urlencoded'
            request_headers['Content-Type'] = kwargs['content_type']
            body = urllib.parse.urlencode(kwargs.pop('body'))
            kwargs['body'] = body.encode()

        kwargs.update({
            'auth_username': self.admin_token,
            'auth_password': '',
            'user_agent': f'imbi/{version} (SonarQubeClient)',
        })
        response = await super().http_fetch(str(url), method=method, **kwargs)
        if not response.ok:
            self.logger.warning('%s %s failed: %s', method, url, response.code)
            if response.body:
                self.logger.warning('response body: %r', response.body)
        return response

    async def create_project(self, project: 'automations.Project', *,
                             main_branch_name='main',
                             public_url: yarl.URL) -> typing.Tuple[str, str]:
        self.logger.info('creating SonarQube project for %s', project.slug)
        response = await self.api('/projects/create', method='POST', body={
            'name': project.name,
            'project': generate_key(project),
        })
        if not response.ok:
            raise errors.InternalServerError(
                'failed to create project %s: %s', project.name, response.code,
                title='SonarQube API Failure', sonar_response=response.body)
        project_key = response.body['project']['key']
        dashboard_url = self.sonar_url.with_path('/dashboard').with_query({
            'id': project_key,
        })

        self.logger.debug('retrieving branches for %s', project_key)
        response = await self.api(
            yarl.URL('/project_branches/list').with_query({
                'project': project_key,
            }))
        if not response.ok:
            self.logger.error('failed to list project branches for %s: %s',
                              project_key, response.code)
        else:
            self.logger.debug('making sure that main branch is %s for %s',
                              main_branch_name, project_key)
            main_branches = [branch
                             for branch in response.body['branches']
                             if branch['isMain']]
            if main_branches and main_branches[0]['name'] != main_branch_name:
                branch = main_branches[0]
                self.logger.info('resetting main branch from %s to %s for %s',
                                 branch['name'], main_branch_name, project_key)
                response = await self.api(
                    '/project_branches/rename', method='POST', body={
                        'project': project_key,
                        'name': main_branch_name,
                    })
                if not response.ok:
                    self.logger.error(
                        'failed to rename main branch %s for %s: %s',
                        branch['name'], project_key, response.code)

        if await self._is_gitlab_alm_available():
            self.logger.debug('checking for PR decoration on %s', project_key)
            response = await self.api(
                yarl.URL('/alm_settings/get_binding').with_query({
                    'project': project_key,
                })
            )
            if response.code == 404:  # not configured or doesn't exist
                response = await self.api(
                    yarl.URL('/alm_settings/set_gitlab_binding'),
                    method='POST',
                    body={
                        'almSetting': self.gitlab_alm_key,
                        'project': project_key,
                        'repository': project.gitlab_project_id,
                    }
                )
                if not response.ok:
                    self.logger.error(
                        'failed to enable PR decoration for %s: %s',
                        project_key, response.code)
            elif not response.ok:
                self.logger.error(
                    'failed to check for GitLab integration for %s: %s',
                    project_key, response.code)

        self.logger.debug('adding link to Imbi project for %s', project_key)
        response = await self.api(
            yarl.URL('/project_links/create'),
            method='POST',
            body={
                'name': 'Imbi Project',
                'projectKey': project_key,
                'url': str(public_url),
            }
        )
        if not response.ok:
            self.logger.error('failed to set the Imbi project link for %s: %s',
                              project_key, response.code)

        return project_key, str(dashboard_url)

    async def _is_gitlab_alm_available(self) -> bool:
        """Check if the SonarQube server has the GitLab ALM configured.

        The result of this method is "remembered" by setting the
        `gitlab_alm_key` class attribute to something other than
        :data:`None`.  It will be set to :data:`False` when we
        determine that the GitLab ALM is not configured or to the
        configured "key" value.

        """
        if self.gitlab_alm_key is None:
            response = await self.api('/alm_settings/list_definitions')
            if response.ok:
                self.__class__.gitlab_alm_key = False
                for connection in response.body.get('gitlab', []):
                    if connection['key'] == 'gitlab':
                        self.logger.info('found GitLab ALM %s',
                                         connection['key'])
                        self.__class__.gitlab_alm_key = connection['key']
                        break
                else:
                    self.logger.warning(
                        'GitLab ALM not found in %r, disabling MR decoration',
                        response.body)
            else:
                self.logger.warning(
                    'failed to list alm_settings for sonar: %s',
                    response.code)
                return False  # don't cache failures for now

        return bool(self.gitlab_alm_key)

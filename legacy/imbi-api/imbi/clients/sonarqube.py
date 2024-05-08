from __future__ import annotations

import logging
import typing
import urllib.parse

import sprockets.mixins.http
import yarl

from imbi import errors, models, version
if typing.TYPE_CHECKING:
    from imbi import app


def generate_key(project: models.Project) -> str:
    """Generate a SonarQube project key for `project`."""
    return ':'.join([project.namespace.slug.lower(), project.slug.lower()])


def generate_dashboard_link(project: models.Project,
                            sonar_settings: dict) -> typing.Union[str, None]:
    """Generate a link to the SonarQube dashboard for `project`."""
    if sonar_settings['url']:
        root = yarl.URL(sonar_settings['url'])
        return str(
            root.with_path('/dashboard').with_query({
                'id': generate_key(project),
            }))


async def create_client(application: app.Application,
                        integration_name: str) -> '_SonarQubeClient':
    logger = logging.getLogger(__package__).getChild('create_client')
    settings = application.settings['automations']['sonarqube']
    if not settings['enabled']:
        raise errors.ClientUnavailableError(integration_name, 'disabled')

    sonarqube_info = await models.integration(integration_name, application)
    if not sonarqube_info:
        logger.warning('%r integration is enabled but not configured',
                       integration_name)
        raise errors.ClientUnavailableError(integration_name, 'not configured')
    if not sonarqube_info.api_secret:
        logger.warning('API secret is missing for %r', integration_name)
        raise errors.ClientUnavailableError(integration_name, 'misconfigured')

    return _SonarQubeClient(yarl.URL(str(sonarqube_info.api_endpoint)),
                            sonarqube_info.api_secret)


class _SonarQubeClient(sprockets.mixins.http.HTTPClientMixin):
    """API Client for SonarQube.

    This client uses the SonarQube HTTP API to automate aspects
    of managing projects.

    """
    gitlab_alm_key: typing.Union[bool, None, str] = None

    def __init__(self, api_endpoint: yarl.URL, api_secret: str, *args,
                 **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__package__).getChild(
            'SonarQubeClient')
        self.api_url = api_endpoint
        self.api_secret = api_secret
        self.url = api_endpoint.with_path('/')

    async def api(self,
                  url: typing.Union[yarl.URL, str],
                  *,
                  method: str = 'GET',
                  **kwargs) -> sprockets.mixins.http.HTTPResponse:
        """Make an authenticated API call."""
        if not isinstance(url, yarl.URL):
            url = yarl.URL(url)
        if not url.is_absolute():
            new_url = self.api_url / url.path.lstrip('/')
            url = new_url.with_query(url.query)

        request_headers = kwargs.setdefault('request_headers', {})
        request_headers['Accept'] = 'application/json'
        if kwargs.get('body', None) is not None:
            kwargs['content_type'] = 'application/x-www-form-urlencoded'
            request_headers['Content-Type'] = kwargs['content_type']
            body = urllib.parse.urlencode(kwargs.pop('body'))
            kwargs['body'] = body.encode()

        kwargs.update({
            'auth_username': self.api_secret,
            'auth_password': '',
            'user_agent': f'imbi/{version} (SonarQubeClient)',
        })
        response = await super().http_fetch(str(url), method=method, **kwargs)
        if not response.ok:
            self.logger.warning('%s %s failed: %s', method, url, response.code)
            if response.body:
                self.logger.warning('response body: %r', response.body)
        return response

    async def create_project(self,
                             project: models.Project,
                             *,
                             main_branch_name='main',
                             public_url: yarl.URL) -> typing.Tuple[str, str]:
        """Create a SonarQube project for `project`.

        :returns: a :class:`tuple` containing the assigned project key
            and a link to the dashboard

        """
        self.logger.info('creating SonarQube project for %s', project.slug)
        response = await self.api('/projects/create',
                                  method='POST',
                                  body={
                                      'name': project.name,
                                      'project': generate_key(project),
                                  })
        if not response.ok:
            raise errors.InternalServerError('failed to create project %s: %s',
                                             project.name,
                                             response.code,
                                             title='SonarQube API Failure',
                                             sonar_response=response.body)
        project_key = response.body['project']['key']
        dashboard_url = self.url.with_path('/dashboard').with_query({
            'id': project_key,
        })

        return project_key, str(dashboard_url)

    async def enable_pr_decoration(self, project_key: str,
                                   gitlab_project_id: int):
        """Enable GitLab MR decoration if it is available."""
        alm_enabled = await self._is_gitlab_alm_available()
        if not alm_enabled:
            return

        self.logger.debug('checking for PR decoration on %s', project_key)
        response = await self.api(
            yarl.URL('/alm_settings/get_binding').with_query({
                'project': project_key,
            }))
        if response.code == 404:  # not configured or doesn't exist
            response = await self.api(
                yarl.URL('/alm_settings/set_gitlab_binding'),
                method='POST',
                body={
                    'almSetting': self.gitlab_alm_key,
                    'project': project_key,
                    'repository': gitlab_project_id,
                })
            if not response.ok:
                self.logger.error('failed to enable PR decoration for %s: %s',
                                  project_key, response.code)
        elif not response.ok:
            self.logger.error(
                'failed to check for GitLab integration for %s: %s',
                project_key, response.code)

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
                    'failed to list alm_settings for sonar: %s', response.code)
                return False  # don't cache failures for now

        return bool(self.gitlab_alm_key)

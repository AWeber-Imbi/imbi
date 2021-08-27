import asyncio
import logging
import typing
import urllib.parse

import sprockets.mixins.http
import tornado.web
import yarl

from imbi import errors, models, version


def generate_key(project: models.Project) -> str:
    """Generate a SonarQube project key for `project`."""
    return ':'.join([project.namespace.slug.lower(), project.slug.lower()])


def generate_dashboard_link(project: models.Project,
                            sonar_settings: dict) -> typing.Union[str, None]:
    """Generate a link to the SonarQube dashboard for `project`."""
    if sonar_settings['url']:
        root = yarl.URL(sonar_settings['url'])
        return str(root.with_path('/dashboard').with_query({
            'id': generate_key(project),
        }))


class SonarQubeClient(sprockets.mixins.http.HTTPClientMixin):
    """API Client for SonarQube.

    This client uses the SonarQube HTTP API to automate aspects
    of managing projects.

    """
    enabled: typing.Union[bool, None] = None
    gitlab_alm_key: typing.Union[bool, None, str] = None

    def __init__(self, application: tornado.web.Application, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.logger = logging.getLogger(__package__).getChild(
            'SonarQubeClient')

        self.settings = application.settings['automations']['sonarqube']
        try:
            self.admin_token = self.settings['admin_token']
            self.sonar_url = yarl.URL(self.settings['url'])
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
                  method: str = 'GET', **kwargs
                  ) -> sprockets.mixins.http.HTTPResponse:
        """Make an authenticated API call."""
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

    async def create_project(self, project: models.Project, *,
                             main_branch_name='main',
                             public_url: yarl.URL) -> typing.Tuple[str, str]:
        """Create a SonarQube project for `project`.

        :returns: a :class:`tuple` containing the assigned project key
            and a link to the dashboard

        """
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

        await asyncio.gather(
            self._fix_main_branch(project_key, main_branch_name),
            self._enable_pr_decoration(project_key, project.gitlab_project_id),
            self._add_link_to_sonar(project_key, 'Imbi Project', public_url),
        )
        return project_key, str(dashboard_url)

    async def _fix_main_branch(self, project_key: str, main_branch_name: str):
        """Sonar assumes that the "main" branch is named master.

        This will cause main branches with any other name to be
        treated as one-off branches.  You can *manually* fix this
        by deleting the branch that was analyzed and renaming the
        "master" branch.  Instead of requiring this for projects,
        this method ensures that the "master" branch in SonarQube
        matches the default branch in the SCM.

        """
        response = await self.api(
            yarl.URL('/project_branches/list').with_query({
                'project': project_key,
            }))
        if not response.ok:
            self.logger.error('failed to list project branches for %s: %s',
                              project_key, response.code)
            return

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

    async def _enable_pr_decoration(self, project_key: str,
                                    gitlab_project_id: int):
        """Enable GitLab MR decoration if it is available."""
        alm_enabled = await self._is_gitlab_alm_available()
        if not alm_enabled:
            return

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
                    'repository': gitlab_project_id,
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

    async def _add_link_to_sonar(self, project_key: str, name: str,
                                 url: yarl.URL):
        """Add a named link to the SonarQube dashboard."""
        self.logger.debug('adding link to Imbi project for %s', project_key)
        response = await self.api(
            yarl.URL('/project_links/create'),
            method='POST',
            body={'name': name, 'projectKey': project_key, 'url': str(url)})
        if not response.ok:
            self.logger.error('failed to set the Imbi project link for %s: %s',
                              project_key, response.code)

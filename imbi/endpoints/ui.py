"""
API Endpoint for returning UI Settings

"""
import typing

from imbi import common
from imbi.endpoints import base, settings


class IndexRequestHandler(base.RequestHandler):

    ENDPOINT = 'ui-index'

    def get(self, *args, **kwargs):
        self.render('index.html')


class LoginRequestHandler(base.RequestHandler):

    ENDPOINT = 'ui-login'

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


class LogoutRequestHandler(base.RequestHandler):

    ENDPOINT = 'ui-logout'

    async def get(self, *args, **kwargs):
        await self.session.clear()
        self.redirect('/')


class SettingsRequestHandler(base.RequestHandler):

    ENDPOINT = 'ui-settings'

    async def get(self, *args, **kwargs):
        sidebar = [
            {
                'title': 'Projects',
                'icon': 'fas fa-cubes',
                'items': [
                    {
                        'title': 'Inventory',
                        'path': '/projects/'
                    }
                ]
            },
            {
                'title': 'Operations',
                'icon': 'fas fa-hat-wizard',
                'items': [
                    {
                        'title': 'Change Log',
                        'path': '/operations/changelog'
                    }
                ]
            }
        ]
        if self._current_user and self._current_user.has_permission('admin'):
            sidebar.append({
                    'title': 'Administration',
                    'icon': 'fas fa-wrench',
                    'items': [
                        {
                            'title': 'Configuration Systems',
                            'path': '/admin/configuration_systems'
                        },
                        {
                            'title': 'Cookie Cutters',
                            'path': '/admin/cookie_cutters'
                        },
                        {
                            'title': 'Data Centers',
                            'path': '/admin/data_centers'
                        },
                        {
                            'title': 'Deployment Types',
                            'path': '/admin/deployment_types'
                        },
                        {
                            'title': 'Environments',
                            'path': '/admin/environments'
                        },
                        {
                            'title': 'Groups',
                            'path': '/admin/groups'
                        },
                        {
                            'title': 'Orchestration Systems',
                            'path': '/admin/orchestration_systems'
                        },
                        {
                            'title': 'Project Fact Types',
                            'path': '/admin/project_fact_types'
                        },
                        {
                            'title': 'Project Link Types',
                            'path': '/admin/project_link_types'
                        },
                        {
                            'title': 'Project Types',
                            'path': '/admin/project_types'
                        },
                        {
                            'title': 'Teams',
                            'path': '/admin/teams'
                        }
                    ]
                })

        self.send_response({
            'service_name': self.application.settings['service'].title(),
            'gitlab_url': self.application.settings['gitlab_url'],
            'ldap_enabled': common.ldap_enabled(),
            'sidebar': sidebar,
            'configuration_systems': await self._get_values(
                settings.ConfigurationSystems.GET_SQL,
                'configuration-systems'),
            'cookie_cutters': await self._get_values(
                settings.CookieCutters.GET_SQL, 'cookie-cutters'),
            'data_centers': await self._get_values(
                settings.DataCenters.GET_SQL, 'data-centers'),
            'deployment_types': await self._get_values(
                settings.DeploymentTypes.GET_SQL, 'deployment-types'),
            'environments': await self._get_values(
                settings.Environments.GET_SQL, 'environments'),
            'orchestration_systems': await self._get_values(
                settings.OrchestrationSystems.GET_SQL,
                'orchestration-systems'),
            'project_link_types': await self._get_values(
                settings.ProjectLinkTypes.GET_SQL, 'project-link-types'),
            'project_types': await self._get_values(
                settings.ProjectTypes.GET_SQL, 'project-types'),
            'teams': await self._get_values(settings.Teams.GET_SQL, 'teams')
        })

    async def _get_values(self, sql: str, name: str) -> typing.List[dict]:
        result = await self.postgres_execute(
            sql, metric_name='settings-get-{}'.format(name))
        return result.rows


class GroupsRequestHandler(base.CRUDRequestHandler):

    ENDPOINT = 'ui-groups'

    GET_SQL = 'SELECT name FROM v1.groups ORDER BY name ASC;'
    TTL = 300


class UserRequestHandler(base.AuthenticatedRequestHandler):

    ENDPOINT = 'ui-user'

    def get(self, *args, **kwargs):
        user = self.current_user.as_dict()
        del user['password']
        self.send_response(user)

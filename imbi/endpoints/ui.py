"""
API Endpoint for returning UI Settings

"""
import typing
from itertools import chain

from imbi import common
from imbi.endpoints import base, settings


class IndexRequestHandler(base.RequestHandler):

    ENDPOINT = 'ui-index'

    def get(self, *args, **kwargs):
        if self.request.path == '/':
            return self.redirect('/ui/')
        self.render('index.html')


class TestRequestHandler(base.RequestHandler):

    ENDPOINT = 'ui-test'

    def get(self, *args, **kwargs):
        self.render('test.html')


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
        self.send_response({
            'service_name': self.application.settings['service'].title(),
            'gitlab_url': self.application.settings['gitlab_url'],
            'ldap_enabled': common.ldap_enabled(),
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
        user['permissions'] = list(set(
            chain.from_iterable([g['permissions'] for g in user['groups']])))
        self.send_response(user)

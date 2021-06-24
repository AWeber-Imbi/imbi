"""
API Endpoint for returning UI Settings

"""
import problemdetails

from imbi import integrations
from imbi.endpoints import base, gitlab


class IndexRequestHandler(base.RequestHandler):

    ENDPOINT = 'ui-index'

    def get(self, *args, **kwargs):
        if self.request.path == '/':
            return self.redirect('/ui/')
        self.render(
            'index.html',
            javascript_url=self.application.settings.get('javascript_url'))


class LoginRequestHandler(base.RequestHandler):

    ENDPOINT = 'ui-login'

    async def post(self, *args, **kwargs):
        body = self.get_request_body()
        if not await self.session.authenticate(
                body.get('username'), body.get('password')):
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
        self.send_response({'loggedOut': True})


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


class GitLabAutomationHandler(base.AuthenticatedRequestHandler):

    NAME = 'GitLabAutomationHandler'
    ENDPOINT = 'ui-gitlab'

    async def prepare(self):
        await super().prepare()
        if not self._finished:
            gitlab_int = await integrations.OAuth2Integration.by_name(
                self.application, 'gitlab')
            if not gitlab_int:
                raise problemdetails.Problem(
                    500, 'application lookup failed for gitlab',
                    title='Integration Missing',
                    detail='GitLab integration is not configured')

            imbi_user = await self.get_current_user()  # never None
            tokens = await gitlab_int.get_user_tokens(imbi_user)
            if not tokens:
                raise problemdetails.Problem(
                    403, 'no gitlab tokens for %r', imbi_user,
                    title='GitLab Not Connected')
            self.gitlab = gitlab.GitLabClient(tokens[0])


class GitLabCreationAutomation(GitLabAutomationHandler,
                               base.ValidatingRequestHandler):
    NAME = 'GitLabCreationAutomation'
    ENDPOINT = 'ui-gitlab-create'

    async def post(self):
        request = self.get_request_body()
        description = request['description']
        project_id = int(request['project_id'])
        project_name = request['name']

        async with self.postgres_transaction() as transaction:
            result = await transaction.execute(
                """
                SELECT p.gitlab_project_id,
                       n.slug AS namespace_slug,
                       n.gitlab_group_name,
                       t.slug AS type_slug,
                       t.gitlab_project_prefix
                  FROM v1.projects AS p
                  JOIN v1.namespaces AS n ON (n.id = p.namespace_id)
                  JOIN v1.project_types AS t ON (t.id = p.project_type_id)
                 WHERE p.id = %(project_id)s
                """,
                {'project_id': project_id})
            if result.row_count == 0:
                raise problemdetails.Problem(
                    400, 'non-existent project %s', project_id,
                    title='Invalid Request',
                    detail=f'{project_id} is not a valid namespace')
            project_info = result.row

            if project_info['gitlab_group_name'] is None:
                raise problemdetails.Problem(
                    400, 'namespace %s does not have a gitlab group',
                    project_info['namespace_slug'],
                    title='Invalid Request',
                    detail=(project_info['namespace_slug'] +
                            ' is not connected to gitlab'))
            if project_info['gitlab_project_prefix'] is None:
                raise problemdetails.Problem(
                    400, 'project type %s does not have a gitlab prefix',
                    project_info['type_slug'], title='Invalid Request',
                    detail=(project_info['type_slug'] +
                            ' is missing a gitlab prefix'))

            parent = await self.gitlab.fetch_group(
                project_info['gitlab_group_name'],
                project_info['gitlab_project_prefix'])
            if parent is None:
                raise problemdetails.Problem(
                    400, 'GitLab parent %s/%s does not exist',
                    project_info['gitlab_group_name'],
                    project_info['gitlab_project_prefix'],
                    title='GitLab Group Not Found')

            project_info = await self.gitlab.create_project(
                parent, project_name, description=description)
            self.logger.info('created GitLab project %s', project_info['id'])
            await transaction.execute(
                """UPDATE v1.projects
                      SET gitlab_project_id = %(gitlab_project_id)s
                    WHERE id = %(project_id)s""",
                {
                    'project_id': project_id,
                    'gitlab_project_id': project_info['id'],
                })

        self.send_response({
            'gitlab_project_id': project_info['id'],
            'gitlab_project_url': project_info['_links']['self'],
        })

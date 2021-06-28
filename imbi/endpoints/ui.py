"""
API Endpoint for returning UI Settings

"""
from imbi import automations, errors, integrations
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
                raise errors.IntegrationNotFound('gitlab')

            imbi_user = await self.get_current_user()  # never None
            tokens = await gitlab_int.get_user_tokens(imbi_user)
            if not tokens:
                raise errors.Forbidden(
                    'no gitlab tokens for %r', imbi_user,
                    title='GitLab Not Connected')
            self.gitlab = gitlab.GitLabClient(tokens[0])


class GitLabCreationAutomation(GitLabAutomationHandler,
                               base.ValidatingRequestHandler):
    NAME = 'GitLabCreationAutomation'
    ENDPOINT = 'ui-gitlab-create'

    async def post(self):
        request = self.get_request_body()
        project_id = int(request['project_id'])

        async with self.postgres_transaction() as transaction:
            result = await transaction.execute(
                """
                SELECT id, description, gitlab_project_id, name, namespace_id,
                       project_type_id, slug
                  FROM v1.projects
                 WHERE id = %(project_id)s
                """,
                {'project_id': project_id})
            if result.row_count == 0:
                raise errors.BadRequest('%s is not a valid imbi project ID',
                                        project_id)

            automation = automations.GitLabCreateProjectAutomation(
                automations.Project.from_database(result.row),
                await self.get_current_user(),
                transaction)
            failures = await automation.prepare()
            if failures:
                if len(failures) == 1:
                    raise errors.BadRequest('Create project failed: %s',
                                            failures[0],
                                            title='Create project failure',
                                            failures=failures)
                else:
                    raise errors.BadRequest(
                        'Create project failed with %s errors', len(failures),
                        title='Create project failure',
                        failures=failures)

            gitlab_info = await automation.run()

        self.send_response({
            'gitlab_project_id': gitlab_info['id'],
            'gitlab_project_url': gitlab_info['_links']['self'],
        })

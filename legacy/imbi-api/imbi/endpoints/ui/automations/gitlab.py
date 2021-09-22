import typing

from imbi import errors, oauth2
from imbi.automations import gitlab as automations
from imbi.clients import gitlab
from imbi.endpoints import base
from imbi.endpoints.ui.automations import mixins


class GitLabAutomationRequestHandler(mixins.PrepareFailureMixin,
                                     base.AuthenticatedRequestHandler):

    NAME = 'ui-gitlab'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.gitlab: typing.Optional[gitlab.GitLabClient] = None

    async def prepare(self):
        await super().prepare()
        if not self._finished:
            integration = await oauth2.OAuth2Integration.by_name(
                self.application, 'gitlab')
            if not integration:
                raise errors.IntegrationNotFound('gitlab')

            user = await self.get_current_user()  # never None
            tokens = await integration.get_user_tokens(user)
            if not tokens:
                raise errors.Forbidden(
                    '%r has no GitLab tokens', user,
                    title='GitLab Not Connected')
            self.gitlab = gitlab.GitLabClient(tokens[0], self.application)


class CreationRequestHandler(GitLabAutomationRequestHandler,
                             base.ValidatingRequestHandler):

    NAME = 'ui-gitlab-create'

    async def post(self):
        request = self.get_request_body()
        project_id = int(request['project_id'])

        async with self.postgres_transaction() as transaction:
            automation = automations.GitLabCreateProjectAutomation(
                self.application, project_id, await self.get_current_user(),
                transaction)
            failures = await automation.prepare()
            if failures:
                raise self.handle_prepare_failures('Create Project', failures)
            gitlab_info = await automation.run()

        self.send_response({
            'gitlab_project_id': gitlab_info.id,
            'gitlab_project_url': gitlab_info.links.self,
        })


class InitialCommitRequestHandler(GitLabAutomationRequestHandler):

    NAME = 'ui-gitlab-commit'

    async def post(self):
        request = self.get_request_body()
        try:
            imbi_project_id = request['project_id']
            cookie_cutter = request['cookie_cutter']
        except KeyError as error:
            raise errors.BadRequest(
                'Error creating initial commit: missing required field %s',
                error.args[0])
        except TypeError as error:
            raise errors.BadRequest('Error creating initial commit: %s', error)

        async with self.postgres_transaction() as transaction:
            automation = automations.GitLabInitialCommitAutomation(
                self.application, imbi_project_id, cookie_cutter,
                await self.get_current_user(), transaction)
            failures = await automation.prepare()
            if failures:
                raise self.handle_prepare_failures('Create Initial Commit',
                                                   failures)
            try:
                commit_info = await automation.run()
            except automations.CookieCutterError as error:
                raise errors.InternalServerError(
                    'Error applying cookiecutter: %s', error)
            except automations.InitialCommitError as error:
                raise errors.InternalServerError(
                    'Error creating initial commit: %s', error)

        self.send_response(commit_info)

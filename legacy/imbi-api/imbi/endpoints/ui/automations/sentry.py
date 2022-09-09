from imbi.automations import sentry
from imbi.endpoints import base
from imbi.endpoints.ui.automations import mixins
from imbi.opensearch import project


class ProjectCreationRequestHandler(mixins.PrepareFailureMixin,
                                    project.RequestHandlerMixin,
                                    base.ValidatingRequestHandler):
    NAME = 'ui-sentry-create-project'

    async def post(self) -> None:
        request = self.get_request_body()
        project_id = int(request['project_id'])
        user = await self.get_current_user()  # never None
        async with self.postgres_transaction() as transaction:
            client = sentry.SentryCreateProjectAutomation(
                self.application, project_id, user, transaction)
            failures = await client.prepare()
            if failures:
                raise self.handle_prepare_failures('Create Project', failures)

            project_info = await client.run()
            self.send_response({'sentry_project_url': project_info.link})

        await self.index_document(project_id)

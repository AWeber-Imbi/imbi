"""
API Endpoint for returning UI Settings

"""
import yarl

from imbi import errors
from imbi.automations import sonarqube
from imbi.endpoints import base
from imbi.endpoints.ui.automations import mixins


class CreationRequestHandler(mixins.PrepareFailureMixin,
                             base.AuthenticatedRequestHandler):

    NAME = 'ui-sonarqube-create'

    async def post(self):
        request = self.get_request_body()
        try:
            imbi_project_id = request['project_id']
        except KeyError as error:
            raise errors.BadRequest('request missing required field %s',
                                    error.args[0])

        if self.settings.get('frontend_url'):
            public_url = yarl.URL(self.settings['frontend_url'])
        else:
            public_url = yarl.URL.build(scheme=self.request.protocol,
                                        host=self.request.host)
        public_url = public_url.with_path(
            self.reverse_url('project', imbi_project_id))

        async with self.postgres_transaction() as transaction:
            automation = sonarqube.SonarCreateProject(
                self.application, imbi_project_id, public_url,
                await self.get_current_user(), transaction)
            failures = await automation.prepare()
            if failures:
                raise self.handle_prepare_failures('Create SonarQube Project',
                                                   failures)
            project_info = await automation.run()
        self.send_response(project_info)

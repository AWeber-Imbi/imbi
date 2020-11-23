"""
Request Handler for the projects inventory

"""
from imbi.endpoints import base

SQL = """\
  SELECT id, created_at, modified_at, "name", slug, description,
         owned_by, data_center, project_type, configuration_system,
         deployment_type, orchestration_system
    FROM v1.projects
ORDER BY owned_by, "name" ASC;"""


class RequestHandler(base.AuthenticatedRequestHandler):

    NAME = 'project-inventory'

    async def get(self, *args, **kwargs):
        if self._respond_with_html:
            return self.render('index.html')
        result = await self.postgres_execute(
            SQL, metric_name='project-inventory')
        self.send_response(result.rows)

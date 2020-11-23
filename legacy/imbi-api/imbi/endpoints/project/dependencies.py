"""
Request Handler for the projects inventory

"""
from imbi.endpoints import base

SQL = """\
  SELECT dependency_id
    FROM v1.project_dependencies
   WHERE project_id = %(project_id)s
ORDER BY dependency_id ASC;"""


class RequestHandler(base.AuthenticatedRequestHandler):

    NAME = 'project-dependencies'

    async def get(self, *args, **kwargs):
        if self._respond_with_html:
            return self.render('index.html')
        result = await self.postgres_execute(
            SQL, kwargs, metric_name='project-dependencies')
        self.send_response(result.rows)

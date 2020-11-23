"""
Request Handler for the project links

"""
from imbi.endpoints import base

SQL = """\
  SELECT project_id, link_type, url
    FROM v1.project_links
   WHERE project_id=%(project_id)s
ORDER BY link_type;"""


class RequestHandler(base.AuthenticatedRequestHandler):

    NAME = 'project-links'

    async def get(self, *args, **kwargs):
        if self._respond_with_html:
            return self.render('index.html')
        result = await self.postgres_execute(
            SQL, kwargs, metric_name='project-links')
        self.send_response(result.rows)

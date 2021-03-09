import re

from . import base


class RequestHandler(base.AuthenticatedRequestHandler):

    NAME = 'dashboard'

    PROJECT_COUNTS = re.sub(r'\s+', ' ', """\
        SELECT a.project_type_id,
               b.name AS name,
               b.plural_name AS plural,
               b.icon_class AS icon,
               b.slug AS slug,
               count(a.*)
          FROM v1.projects AS a
          JOIN v1.project_types AS b
            ON b.id = a.project_type_id
         GROUP BY a.project_type_id, b.name, b.plural_name, b.icon_class,
                  b.slug
         ORDER BY count(a.*) DESC""")

    async def get(self):
        stats = await self.postgres_execute(
            self.PROJECT_COUNTS, metric_name='dashboard-project-types')
        self.send_response({'project_types': stats.rows})

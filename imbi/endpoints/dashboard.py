import re

from . import base


class RequestHandler(base.AuthenticatedRequestHandler):

    NAME = 'dashboard'

    NAMESPACE_COUNTS = re.sub(r'\s+', ' ', """\
        SELECT a.namespace_id,
               b.name AS name,
               b.icon_class AS icon,
               count(a.*)
          FROM v1.projects AS a
          JOIN v1.namespaces AS b
            ON b.id = a.namespace_id
         WHERE archived IS FALSE
         GROUP BY a.namespace_id, b.name, b.icon_class
         ORDER BY b.name ASC""")

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
         WHERE archived IS FALSE
         GROUP BY a.project_type_id, b.name, b.plural_name, b.icon_class,
                  b.slug
         ORDER BY count(a.*) DESC""")

    async def get(self):
        namespaces = await self.postgres_execute(
            self.NAMESPACE_COUNTS, metric_name='dashboard-namespaces')
        project_types = await self.postgres_execute(
            self.PROJECT_COUNTS, metric_name='dashboard-project-types')
        self.send_response({
            'namespaces': namespaces.rows,
            'project_types': project_types.rows})

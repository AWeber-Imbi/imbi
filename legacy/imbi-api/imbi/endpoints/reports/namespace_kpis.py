import re

from tornado import web

from imbi.endpoints import base


class RequestHandler(base.RequestHandler):

    NAME = 'reports-kpis'

    SQL = re.sub(r'\s+', ' ', """\
        WITH project_scores AS (
            SELECT a.namespace_id,
                   b.name AS namespace,
                   a.id,
                   v1.project_score(a.id)
              FROM v1.projects AS a
              JOIN v1.namespaces AS b
                ON b.id = a.namespace_id)
        SELECT namespace_id,
               namespace,
               count(*) AS projects,
               percentile_disc(0.75)
                 WITHIN GROUP (ORDER BY project_score) AS stack_health_score,
               sum(project_score)::INT AS total_project_score,
               count(*) * 100 AS total_possible_project_score,
               (((sum(project_score)::NUMERIC(9,2)
                   / (count(*) * 100)::NUMERIC(9,2))
                 * 100)::NUMERIC(9,2))::TEXT || '%' AS percent_of_tpps
          FROM project_scores
         GROUP BY namespace_id, namespace
         ORDER BY namespace;""")

    @web.authenticated
    async def get(self):
        result = await self.postgres_execute(
            self.SQL, metric_name='reports-compliance')
        self.send_response(result.rows)

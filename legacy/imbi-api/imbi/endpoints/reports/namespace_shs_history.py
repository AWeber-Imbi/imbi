import re

from imbi.endpoints import base


class RequestHandler(base.AuthenticatedRequestHandler):

    NAME = 'reports-namespace-shs-history'

    SQL = re.sub(
        r'\s+', ' ', """\
        SELECT a.namespace_id,
               a.scored_on,
               a.health_score
          FROM v1.namespace_kpi_history AS a
          JOIN v1.namespaces AS b
            ON b.id = a.namespace_id
         WHERE a.scored_on > CURRENT_DATE - interval '1 year'
      ORDER BY a.scored_on ASC, a.namespace_id ASC;""")

    async def get(self):
        result = await self.postgres_execute(self.SQL, metric_name=self.NAME)
        self.send_response(result.rows)

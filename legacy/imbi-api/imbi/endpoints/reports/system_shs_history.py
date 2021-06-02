import re

from tornado import web

from imbi.endpoints import base


class RequestHandler(base.RequestHandler):

    NAME = 'reports-system-shs-history'

    SQL = re.sub(r'\s+', ' ', """\
        SELECT scored_on,
               ((sum(total_project_score) / sum(total_possible_score))
                    * 100::FLOAT)::NUMERIC(9,2) AS health_score
          FROM v1.namespace_kpi_history
      GROUP BY scored_on
      ORDER BY scored_on ASC""")

    @web.authenticated
    async def get(self):
        result = await self.postgres_execute(self.SQL, metric_name=self.NAME)
        self.send_response(result.rows)

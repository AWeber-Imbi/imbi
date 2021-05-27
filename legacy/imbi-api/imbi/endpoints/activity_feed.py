import re

from tornado import web

from imbi.endpoints import base


class RequestHandler(base.ValidatingRequestHandler):

    NAME = 'activity-feed'

    SQL = re.sub(r'\s+', ' ', """\
        SELECT "when", namespace_id, namespace, project_id, project_name,
                project_type, who, display_name, email_address, what
          FROM v1.activity_feed
         ORDER BY "when" DESC
        OFFSET {offset}
         LIMIT {limit};""")

    @web.authenticated
    async def get(self):
        result = await self.postgres_execute(
            self.SQL.format(
                limit=int(self.get_query_argument('limit', '25')),
                offset=int(self.get_query_argument('offset', '0'))),
            metric_name='reports-compliance')
        self.send_response(result.rows)

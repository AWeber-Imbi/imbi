import re

from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):

    NAME = 'project-fact-history'
    ID = 'project_id'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT a.fact_type_id,
               a.recorded_at,
               a.value,
               a.score,
               a.weight,
               b.icon_class,
               c.display_name AS recorded_by
          FROM v1.project_fact_history AS a
          LEFT JOIN v1.project_fact_type_enums AS b
            ON a.fact_type_id = b.fact_type_id
           AND a.value = b.value
          LEFT JOIN v1.users as c
            ON a.recorded_by = c.username
         WHERE a.project_id = %(project_id)s
         ORDER BY a.recorded_at DESC
         LIMIT %(limit)s OFFSET %(offset)s""")

    async def get(self, *args, **kwargs):
        kwargs['limit'] = int(self.get_query_argument('limit', '25'))
        kwargs['offset'] = int(self.get_query_argument('offset', '0'))

        result = await self.postgres_execute(
            self.COLLECTION_SQL, kwargs,
            metric_name='get-{}'.format(self.NAME))
        self.send_response(result.rows)

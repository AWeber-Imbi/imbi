import re
import typing

import problemdetails
from psycopg2 import errors

from imbi import common
from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):

    NAME = 'project-fact-types'
    ID_KEY = 'project_id'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT a.fact_type_id,
               b.name,
               a.recorded_at,
               a.recorded_by,
               a.value,
               b.data_type,
               CASE WHEN b.fact_type = 'enum' THEN (
                        SELECT score
                          FROM v1.project_fact_type_enums
                         WHERE project_id = a.project_id
                           AND fact_type_id = a.fact_type_id
                           AND value = a.value)
                    WHEN b.fact_type = 'range' THEN (
                        SELECT score
                          FROM v1.project_fact_type_ranges
                         WHERE project_id = a.project_id
                           AND fact_type_id = a.fact_type_id
                           AND a.value::NUMERIC(9,2) BETWEEN min_value
                                                         AND max_value)
                    ELSE 0 END AS score,
                b.weight
          FROM v1.project_facts AS a
          JOIN v1.project_fact_types AS b
            ON b.id = a.fact_type_id
         WHERE a.project_id = %(project_id)s
        ORDER BY b.name""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.project_facts
                    (project_id, fact_type_id, recorded_at, recorded_by, value)
             VALUES (%(project_id)s, %(fact_type_id)s, CURRENT_TIMESTAMP,
                     %(username)s, %(value)s)
        ON CONFLICT (project_id, fact_type_id)
          DO UPDATE SET recorded_at = CURRENT_TIMESTAMP,
                        recorded_by = %(username)s,
                        value = %(value)s""")

    async def get(self, *args, **kwargs):
        result = await self.postgres_execute(
            self.COLLECTION_SQL, self._get_query_kwargs(kwargs),
            'get-{}'.format(self.NAME))
        self.send_response(common.coerce_project_fact_values(result.rows))

    async def post(self, *args, **kwargs):
        for fact in self.get_request_body():
            fact.update({
                'project_id': kwargs['project_id'],
                'username': self._current_user.username
            })
            await self.postgres_execute(
                self.POST_SQL, fact, 'post-{}'.format(self.NAME))
        self.set_status(204)

    def on_postgres_error(self,
                          metric_name: str,
                          exc: Exception) -> typing.Optional[Exception]:
        """Invoked when an error occurs when executing a query

        If `tornado-problem-details` is available,
        :exc:`problemdetails.Problem` will be raised instead of
        :exc:`tornado.web.HTTPError`.

        Override for different error handling behaviors.

        Return an exception if you would like for it to be raised, or swallow
        it here.

        """
        if isinstance(exc, errors.lookup('P0001')):
            return problemdetails.Problem(
                status_code=400, title='Bad Request',
                detail=str(exc).split('\n')[0])
        super().on_postgres_error(metric_name, exc)

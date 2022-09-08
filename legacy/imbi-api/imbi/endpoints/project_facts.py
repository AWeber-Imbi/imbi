from __future__ import annotations

import re
import typing

import psycopg2.errors

from imbi import common, errors
from imbi.endpoints import base
from imbi.opensearch import project


class CollectionRequestHandler(project.RequestHandlerMixin,
                               base.CollectionRequestHandler):

    NAME = 'project-fact-types'
    ID_KEY = 'project_id'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        WITH project_type_id AS (SELECT project_type_id AS id
                                   FROM v1.projects
                                  WHERE id = %(project_id)s)
        SELECT a.id AS fact_type_id,
               a.name,
               b.recorded_at,
               b.recorded_by,
               b.value,
               a.data_type,
               a.ui_options,
               CASE WHEN b.value IS NULL THEN 0
                    ELSE CASE WHEN a.fact_type = 'enum' THEN (
                                          SELECT score::NUMERIC(9,2)
                                            FROM v1.project_fact_type_enums
                                           WHERE fact_type_id = b.fact_type_id
                                             AND value = b.value)
                              WHEN a.fact_type = 'range' THEN (
                                          SELECT score::NUMERIC(9,2)
                                            FROM v1.project_fact_type_ranges
                                           WHERE fact_type_id = b.fact_type_id
                                             AND b.value::NUMERIC(9,2)
                                         BETWEEN min_value AND max_value)
                              WHEN a.data_type = 'boolean' AND b.value = 'true'
                              THEN 100
                              ELSE 0
                          END
                END AS score,
               a.weight
          FROM v1.project_fact_types AS a
     LEFT JOIN v1.project_facts AS b
            ON b.fact_type_id = a.id
           AND b.project_id = %(project_id)s
         WHERE (SELECT id FROM project_type_id) = ANY(a.project_type_ids)
        ORDER BY a.name""")

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
        facts = await self._coerce_facts(self.get_request_body())
        for fact in facts:
            fact.update({
                'project_id': kwargs['project_id'],
                'username': self._current_user.username
            })
            await self.postgres_execute(
                self.POST_SQL, fact, 'post-{}'.format(self.NAME))
        await self.index_document(kwargs['project_id'])
        self.set_status(204)

    async def _coerce_facts(self, facts: list[dict]) -> list[dict]:
        """Take a list of project facts and coerce their values.

        This method looks up the data types and then calls
        :func:`common.coerce_project_fact_values` to perform
        the coercion appropriately.

        """
        result = await self.postgres_execute(
            'SELECT id, data_type'
            '  FROM v1.project_fact_types'
            ' WHERE id IN %(fact_type_ids)s',
            {'fact_type_ids': tuple(fact['fact_type_id'] for fact in facts)},
        )
        fact_type_map = {row['id']: row['data_type'] for row in result.rows}
        for fact in facts:
            try:
                fact_type = fact_type_map[fact['fact_type_id']]
            except KeyError:
                raise errors.BadRequest('%s is not a known fact type id',
                                        fact['fact_type_id'])
            else:
                fact['data_type'] = fact_type

        try:
            return common.coerce_project_fact_values(facts)
        except ValueError as error:
            raise errors.BadRequest('invalid fact value: %s', error)

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
        if isinstance(exc, psycopg2.errors.lookup('P0001')):
            return errors.BadRequest(str(exc).split('\n')[0])
        super().on_postgres_error(metric_name, exc)

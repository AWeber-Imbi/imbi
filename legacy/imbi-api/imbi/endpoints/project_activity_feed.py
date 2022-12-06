import asyncio
import datetime
import re

from tornado import web

from imbi.endpoints import base


class CollectionRequestHandler(base.PaginatedRequestMixin,
                               base.ValidatingRequestHandler):

    NAME = 'project-activity-feed'

    PROJECT_FEED_SQL = re.sub(
        r'\s+', ' ', """
        WITH created AS (
          SELECT created_at AS "when", created_by AS who,
                 'created' AS what, NULL AS fact_name, NULL AS value
            FROM v1.projects
           WHERE id = %(project_id)s
        ),
        updated AS (
          SELECT last_modified_at AS "when", last_modified_by AS who,
                 'updated' AS what, NULL AS fact_name, NULL AS value
            FROM v1.projects
           WHERE id = %(project_id)s
        ),
        facts AS (
          SELECT a.recorded_at AS "when", a.recorded_by AS who,
                 'updated fact' AS what, b.name AS fact_name, a.value
            FROM v1.project_facts AS a
            JOIN v1.project_fact_types AS b
              ON b.id = a.fact_type_id
           WHERE a.project_id = %(project_id)s
        ),
        combined AS (
                SELECT * FROM created
          UNION SELECT * FROM updated
          UNION SELECT * FROM facts
        )
        SELECT 'ProjectFeedEntry' AS "type", c."when", c.who, u.display_name,
               c.what, c.fact_name, c.value
          FROM combined AS c
          JOIN v1.users AS u ON u.username = c.who
         WHERE c."when" >  %(earlier)s
           AND c."when" <= %(later)s
         ORDER BY c."when" DESC
         LIMIT %(remaining)s
        """)

    OPERATIONS_LOG_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT 'OperationsLogEntry' AS "type", o.id,
               o.recorded_at, o.recorded_by, o.completed_at,
               o.project_id, o.environment, o.change_type,
               o.description, o.link, o.notes, o.ticket_slug,
               o.version, p.name AS project_name, u.email_address,
               u.display_name
          FROM v1.operations_log AS o
          JOIN v1.projects AS p ON p.id = o.project_id
          LEFT JOIN v1.users AS u ON u.username = o.recorded_by
         WHERE p.id = %(project_id)s
           AND recorded_at >  %(earlier)s
           AND recorded_at <= %(later)s
         ORDER BY o.recorded_at DESC, o.id DESC
         LIMIT %(remaining)s
        """)

    EARLIEST_EVENT_SQL = re.sub(
        r'\s+', ' ', """\
        WITH T AS (
          SELECT created_at AS earliest
            FROM v1.projects
           WHERE id = %(project_id)s
          UNION
          SELECT MIN(recorded_at) AS earliest
            FROM v1.operations_log
           WHERE project_id = %(project_id)s
        )
        SELECT COALESCE(MIN(earliest), CURRENT_TIMESTAMP) AS earliest
          FROM T
        """)

    @web.authenticated
    async def get(self, project_id: str) -> None:
        token = await self._get_pagination_token(project_id)
        buckets = await self.fetch_items(token,
                                         self._retrieve_rows,
                                         datetime.timedelta(days=90),
                                         project_id=project_id)
        self.send_response(buckets)

    async def _retrieve_rows(
            self, params: dict) -> list[tuple[datetime.datetime, dict]]:
        activity_feed, ops_log = await asyncio.gather(
            self.postgres_execute(self.PROJECT_FEED_SQL, params),
            self.postgres_execute(self.OPERATIONS_LOG_SQL, params))
        self.logger.debug('fetched page containing %s activity, %s ops log',
                          len(activity_feed), len(ops_log))

        all_rows = [(row['when'], row) for row in activity_feed]
        all_rows.extend((row['recorded_at'], row) for row in ops_log)

        return all_rows

    async def _get_pagination_token(self, project_id) -> base.PaginationToken:
        token = self.get_pagination_token_from_request()
        if token is None:
            result = await self.postgres_execute(self.EARLIEST_EVENT_SQL,
                                                 {'project_id': project_id})
            token = base.PaginationToken(
                start=datetime.datetime.now(datetime.timezone.utc),
                limit=int(self.get_query_argument('limit', '25')),
                earliest=result.row['earliest'],
            )
        return token

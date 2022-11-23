from __future__ import annotations

import asyncio
import datetime
import re
import typing

from tornado import web

from imbi.endpoints import base


class CollectionRequestHandler(base.PaginatedRequestMixin,
                               base.ValidatingRequestHandler):

    NAME = 'activity-feed'

    PROJECT_FEED_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT 'ProjectFeedEntry' AS "type", "when",
               namespace_id, namespace, project_id, project_name,
               project_type, who, display_name, email_address,
               what
          FROM v1.activity_feed
         WHERE "when" >  %(earlier)s
           AND "when" <= %(later)s
         ORDER BY "when" DESC
         LIMIT %(remaining)s
        """)

    OPERATIONS_LOG_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT 'OperationsLogEntry' AS "type", o.id,
               o.recorded_at, o.recorded_by, o.completed_at,
               o.project_id, o.environment, o.change_type,
               o.description, o.link, o.notes, o.ticket_slug,
               o.version, p.name AS project_name,
               u.email_address, u.display_name
          FROM v1.operations_log AS o
          LEFT JOIN v1.projects AS p ON p.id = o.project_id
          LEFT JOIN v1.users AS u ON u.username = o.recorded_by
         WHERE recorded_at >  %(earlier)s
           AND recorded_at <= %(later)s
         ORDER BY o.recorded_at DESC, o.id DESC
         LIMIT %(remaining)s
        """)

    EARLIEST_EVENT_SQL = re.sub(
        r'\s+', ' ', """\
        WITH T AS (
            SELECT MIN("when") AS earliest FROM v1.activity_feed
            UNION
            SELECT MIN(recorded_at) AS earliest FROM v1.operations_log
        )
        SELECT COALESCE(MIN(earliest), CURRENT_TIMESTAMP) AS earliest
          FROM T
        """)

    @web.authenticated
    async def get(self):
        token = await self._get_pagination_token()
        buckets = await self.fetch_items(
            token,
            self._retrieve_rows,
            datetime.timedelta(days=10),
            omit_users=set(self.get_query_arguments('omit_user')))

        self.send_response(buckets)

    async def _retrieve_rows(
            self, params) -> list[tuple[datetime.datetime, typing.Any]]:
        activity_feed, ops_log = await asyncio.gather(
            self.postgres_execute(self.PROJECT_FEED_SQL, params),
            self.postgres_execute(self.OPERATIONS_LOG_SQL, params))
        self.logger.debug('fetched page containing %s activity, %s ops log',
                          len(activity_feed), len(ops_log))

        all_rows = [(row['when'], row) for row in activity_feed
                    if row['who'] not in params['omit_users']]
        all_rows.extend((row['recorded_at'], row) for row in ops_log
                        if row['recorded_by'] not in params['omit_users'])

        return all_rows

    async def _get_pagination_token(self):
        token = self.get_pagination_token_from_request()
        if token is None:
            self.logger.info('creating new token')
            result = await self.postgres_execute(self.EARLIEST_EVENT_SQL)
            token = base.PaginationToken(
                start=datetime.datetime.now(datetime.timezone.utc),
                limit=int(self.get_query_argument('limit', '25')),
                earliest=result.row['earliest'],
            )
        return token

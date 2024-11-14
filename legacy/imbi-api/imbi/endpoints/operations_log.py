import datetime
import re

import typing_extensions as typing
from urllib import parse

import yarl

from imbi import errors, opensearch
from imbi.endpoints import base
from imbi.opensearch import operations_log


class _RequestHandlerMixin:
    ID_KEY = 'id'
    FIELDS = [
        'change_type', 'completed_at', 'performed_by', 'description',
        'environment', 'id', 'link', 'notes', 'occurred_at', 'project_id',
        'recorded_at', 'recorded_by', 'ticket_slug', 'version'
    ]

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT o.id, o.recorded_at, o.recorded_by, o.completed_at,
               o.project_id, o.environment, o.change_type, o.description,
               o.link, o.notes, o.ticket_slug, o.version,
               COALESCE(
                  u.email_address,
                  COALESCE(u2.email_address, 'UNKNOWN')
               ) AS email_address,
               COALESCE(
                  u.display_name,
                  COALESCE(u2.display_name, o.recorded_by)
               ) AS display_name,
               p.name AS project_name,
               'OperationsLogEntry' AS "type",
               o.occurred_at,
               o.performed_by
          FROM v1.operations_log AS o
          LEFT JOIN v1.users AS u ON u.username = o.performed_by
          LEFT JOIN v1.users AS u2 ON u2.username = o.recorded_by
          LEFT JOIN v1.projects AS p ON p.id = o.project_id
         WHERE o.id = %(id)s""")


class CollectionRequestHandler(operations_log.RequestHandlerMixin,
                               _RequestHandlerMixin,
                               base.CollectionRequestHandler):
    NAME = 'operations-logs'
    ITEM_NAME = 'operations-log'

    COLLECTION_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT o.id, o.recorded_at, o.recorded_by, o.completed_at,
               o.project_id, o.environment, o.change_type, o.description,
               o.link, o.notes, o.ticket_slug, o.version,
               p.name AS project_name,
               COALESCE(
                   u.email_address,
                   COALESCE(u2.email_address, 'UNKNOWN')
               ) AS email_address,
               COALESCE(
                   u.display_name,
                   COALESCE(u2.display_name, o.recorded_by)
               ) AS display_name,
               'OperationsLogEntry' as "type", o.occurred_at, o.performed_by
          FROM v1.operations_log AS o
          LEFT JOIN v1.users AS u ON u.username = o.performed_by
          LEFT JOIN v1.users AS u2 ON u2.username = o.recorded_by
          LEFT JOIN v1.projects AS p ON p.id = o.project_id
          {{WHERE}}
      ORDER BY o.occurred_at {{ORDER}}, o.id {{ORDER}}
         LIMIT %(limit)s""")

    VALUE_FILTER_CHUNK = re.sub(
        r'\s+', ' ', """\
        ((o.occurred_at = %(recorded_at_anchor)s AND o.id {{OP}} %(id_anchor)s)
        OR o.occurred_at {{OP}} %(recorded_at_anchor)s)""")

    FILTER_CHUNKS = {
        'from': 'o.occurred_at >= %(from)s',
        'to': 'o.occurred_at < %(to)s',
        'project_id': 'o.project_id = %(project_id)s',
        'namespace_id': 'p.namespace_id = %(namespace_id)s',
    }

    POST_SQL = re.sub(
        r'\s+', ' ', """\
        INSERT INTO v1.operations_log
                    (recorded_by, recorded_at, completed_at, occurred_at,
                     project_id, environment, change_type, description,
                     link, notes, ticket_slug, version, performed_by)
             VALUES (%(username)s, CURRENT_TIMESTAMP, %(completed_at)s,
                     %(occurred_at)s, %(project_id)s, %(environment)s,
                     %(change_type)s, %(description)s, %(link)s, %(notes)s,
                     %(ticket_slug)s, %(version)s, %(performed_by)s)
          RETURNING id""")

    async def get(self, *args, **kwargs):
        kwargs['limit'] = int(self.get_query_argument('limit', '100')) + 1
        order = self.get_query_argument('order', 'desc')
        kwargs['from'] = self.get_query_argument('from', None)
        kwargs['to'] = self.get_query_argument('to', None)
        kwargs['namespace_id'] = self.get_query_argument('namespace_id', None)
        kwargs['project_id'] = self.get_query_argument('project_id', None)
        kwargs['recorded_at_anchor'] = self.get_query_argument(
            'recorded_at_anchor', None)
        kwargs['id_anchor'] = self.get_query_argument('id_anchor', None)
        page_direction = self.get_query_argument('page_direction', None)
        is_link = (page_direction is not None
                   and kwargs['recorded_at_anchor'] is not None
                   and kwargs['id_anchor'] is not None)

        where_chunks = []
        for kwarg in self.FILTER_CHUNKS.keys():
            if kwargs[kwarg] is not None:
                where_chunks.append(self.FILTER_CHUNKS[kwarg])
        if is_link:
            if (order == 'asc' and page_direction == 'next') or \
                    (order == 'desc' and page_direction == 'previous'):
                op = '>'
            else:
                op = '<'
            where_chunks.append(self.VALUE_FILTER_CHUNK.replace('{{OP}}', op))
        where_sql = ''
        if where_chunks:
            where_sql = 'WHERE {}'.format(' AND '.join(where_chunks))

        if page_direction == 'previous':
            order = 'desc' if order == 'asc' else 'asc'

        sql = self.COLLECTION_SQL \
            .replace('{{WHERE}}', where_sql) \
            .replace('{{ORDER}}', order)

        result = await self.postgres_execute(sql,
                                             kwargs,
                                             metric_name='get-{}'.format(
                                                 self.NAME))
        rows = result.rows

        if page_direction == 'previous':
            rows = list(reversed(rows))

        next_needed, previous_needed = False, False
        if len(rows) == kwargs['limit']:
            if not is_link or page_direction == 'next':
                rows.pop(-1)
                next_needed = True
            else:
                rows.pop(0)
                previous_needed = True
        if page_direction == 'next':
            previous_needed = True
        elif page_direction == 'previous':
            next_needed = True

        request_url = yarl.URL(self.request.full_url())
        if next_needed:
            next_anchor = rows[-1]
            query = dict(request_url.query)
            query.update({
                'recorded_at_anchor': next_anchor['occurred_at'],
                'id_anchor': next_anchor['id'],
                'page_direction': 'next',
            })
            query_string = parse.urlencode(query)
            self._links['next'] = self.request.path + '?' + query_string
        if previous_needed:
            previous_anchor = rows[0]
            query = dict(request_url.query)
            query.update({
                'recorded_at_anchor': previous_anchor['occurred_at'],
                'id_anchor': previous_anchor['id'],
                'page_direction': 'previous',
            })
            query_string = parse.urlencode(query)
            self._links['previous'] = self.request.path + '?' + query_string

        self.send_response(rows)

    async def post(self, *_args, **kwargs):
        request = self.get_request_body()
        if not request.get('description', '').strip():
            raise errors.BadRequest(
                'Invalid description',
                detail='The request did not validate',
                errors=["'description' is required to be a non-empty string"])

        overrides = {}
        if not request.get('occurred_at'):
            # implement INSERT ... DEFAULT since using `psycopg2.sql.DEFAULT`
            # gets lost somewhere in the stack :/
            overrides['occurred_at'] = datetime.datetime.now(
                datetime.timezone.utc)
        if request.get('performed_by') == self._current_user.username:
            overrides['performed_by'] = None

        result = await self._post(kwargs, overrides)
        await self.index_document(result['id'])


class RecordRequestHandler(operations_log.RequestHandlerMixin,
                           _RequestHandlerMixin, base.CRUDRequestHandler):
    NAME = 'operations-log'

    DELETE_SQL = 'DELETE FROM v1.operations_log WHERE id = %(id)s;'

    PATCH_SQL = re.sub(
        r'\s+', ' ', """\
        UPDATE v1.operations_log
           SET occurred_at = %(occurred_at)s,
               completed_at = %(completed_at)s,
               performed_by = %(performed_by)s,
               project_id = %(project_id)s,
               environment = %(environment)s,
               change_type = %(change_type)s,
               description = %(description)s,
               link = %(link)s,
               notes = %(notes)s,
               ticket_slug = %(ticket_slug)s,
               version = %(version)s
         WHERE id = %(id)s""")

    async def delete(self, *args, **kwargs):
        await super().delete(*args, **kwargs)
        await self.search_index.delete_document(kwargs['id'])

    async def patch(self, *args, **kwargs):
        await super().patch(*args, **kwargs)
        await self.index_document(kwargs['id'])

    def _check_validity(self, instance: dict[str, typing.Any]) -> bool:
        if instance.get('performed_by') == self._current_user.username:
            instance['performed_by'] = None
        return bool(instance.get('description') or '')


class SearchIndexRequestHandler(opensearch.SearchIndexRequestHandler,
                                operations_log.RequestHandlerMixin,
                                base.ValidatingRequestHandler):
    SQL = re.sub(
        r'\s+', ' ', """\
        SELECT id
          FROM v1.operations_log
         ORDER BY id""")

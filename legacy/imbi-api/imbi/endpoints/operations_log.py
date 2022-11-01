import re
from urllib import parse

import yarl

from imbi import models
from imbi.endpoints import base
from imbi.opensearch import operations_log


class _RequestHandlerMixin:
    ID_KEY = 'id'
    FIELDS = ['id', 'recorded_at', 'recorded_by', 'completed_at', 'project_id',
              'environment', 'change_type', 'description', 'link', 'notes',
              'ticket_slug', 'version']

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, recorded_at, recorded_by, completed_at,
               project_id, environment, change_type, description,
               link, notes, ticket_slug, version
          FROM v1.operations_log
         WHERE id = %(id)s""")


class CollectionRequestHandler(operations_log.RequestHandlerMixin,
                               _RequestHandlerMixin,
                               base.CollectionRequestHandler):
    NAME = 'operations-logs'
    ITEM_NAME = 'operations-log'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT o.id, o.recorded_at, o.recorded_by, o.completed_at,
               o.project_id, o.environment, o.change_type, o.description,
               o.link, o.notes, o.ticket_slug, o.version
          FROM v1.operations_log AS o
          {{JOIN}} {{WHERE}}
      ORDER BY o.recorded_at {{ORDER}}, o.id {{ORDER}}
         LIMIT %(limit)s""")

    VALUE_FILTER_CHUNK = re.sub(r'\s+', ' ', """\
        ((o.recorded_at = %(recorded_at_anchor)s AND o.id {{OP}} %(id_anchor)s)
        OR o.recorded_at {{OP}} %(recorded_at_anchor)s)""")

    FILTER_CHUNKS = {
        'from': 'o.recorded_at >= %(from)s',
        'to': 'o.recorded_at < %(to)s',
        'project_id': 'o.project_id = %(project_id)s',
        'namespace_id': 'p.namespace_id = %(namespace_id)s',
    }

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.operations_log
                    (recorded_by, recorded_at, completed_at,
                     project_id, environment, change_type, description,
                     link, notes, ticket_slug, version)
             VALUES (%(recorded_by)s, %(recorded_at)s, %(completed_at)s,
                     %(project_id)s, %(environment)s, %(change_type)s,
                     %(description)s, %(link)s, %(notes)s, %(ticket_slug)s,
                     %(version)s)
          RETURNING id""")

    async def get(self, *args, **kwargs):
        kwargs['limit'] = int(self.get_query_argument('limit', '100')) + 1
        order = self.get_query_argument('order', 'desc')
        kwargs['from'] = self.get_query_argument('from', None)
        kwargs['to'] = self.get_query_argument('to', None)
        kwargs['namespace_id'] = self.get_query_argument('namespace_id', None)
        kwargs['project_id'] = self.get_query_argument('project_id', None)
        kwargs['recorded_at_anchor'] = self.get_query_argument(
            'recorded_at_anchor',
            None)
        kwargs['id_anchor'] = self.get_query_argument('id_anchor', None)
        page_direction = self.get_query_argument('page_direction', None)
        is_link = (page_direction is not None
                   and kwargs['recorded_at_anchor'] is not None
                   and kwargs['id_anchor'] is not None)

        join_sql = ''
        if kwargs['namespace_id'] is not None:
            join_sql += 'JOIN v1.projects AS p ON o.project_id = p.id'

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
            .replace('{{JOIN}}', join_sql) \
            .replace('{{WHERE}}', where_sql) \
            .replace('{{ORDER}}', order)

        result = await self.postgres_execute(
            sql, kwargs, metric_name='get-{}'.format(self.NAME))
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
                'recorded_at_anchor': next_anchor['recorded_at'],
                'id_anchor': next_anchor['id'],
                'page_direction': 'next',
            })
            query_string = parse.urlencode(query)
            self._links['next'] = self.request.path + '?' + query_string
        if previous_needed:
            previous_anchor = rows[0]
            query = dict(request_url.query)
            query.update({
                'recorded_at_anchor': previous_anchor['recorded_at'],
                'id_anchor': previous_anchor['id'],
                'page_direction': 'previous',
            })
            query_string = parse.urlencode(query)
            self._links['previous'] = self.request.path + '?' + query_string

        self.send_response(rows)

    async def post(self, *_args, **kwargs):
        result = await self._post(kwargs)
        await self.index_document(result['id'])


class RecordRequestHandler(operations_log.RequestHandlerMixin,
                           _RequestHandlerMixin,
                           base.CRUDRequestHandler):
    NAME = 'operations-log'

    DELETE_SQL = 'DELETE FROM v1.operations_log WHERE id = %(id)s;'

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.operations_log
           SET recorded_by = %(recorded_by)s,
               recorded_at = %(recorded_at)s,
               completed_at = %(completed_at)s,
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


class SearchIndexRequestHandler(operations_log.RequestHandlerMixin,
                                base.ValidatingRequestHandler):
    SQL = re.sub(r'\s+', ' ', """\
        SELECT id
          FROM v1.operations_log
         ORDER BY id""")

    async def post(self):
        result = await self.postgres_execute(self.SQL)
        for row in result:
            value = await models.operations_log(row['id'],
                                                self.application)
            await self.search_index.index_document(value)

        self.send_response({
            'status': 'ok',
            'message': f'Queued {len(result)} operations log entries for '
                       'indexing'})

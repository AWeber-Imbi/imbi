import re

from tornado import web

from imbi.endpoints import base


class _RequestHandlerMixin:

    ITEM_NAME = 'project'
    ID_KEY = ['id']
    FIELDS = ['id', 'namespace_id', 'project_type_id', 'name', 'slug',
              'description', 'data_center', 'environments', 'deployment_type',
              'configuration_system', 'orchestration_system']
    TTL = 300

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT a.id,
               a.created_at,
               a.created_by,
               a.last_modified_at,
               a.last_modified_by,
               a.namespace_id,
               b.name AS namespace,
               a.project_type_id,
               c.name AS project_type,
               a.name,
               a.slug,
               a.description,
               a.data_center,
               a.environments,
               a.configuration_system,
               a.deployment_type,
               a.orchestration_system
          FROM v1.projects AS a
          JOIN v1.namespaces AS b ON b.id = a.namespace_id
          JOIN v1.project_types AS c ON c.id = a.project_type_id
         WHERE a.id=%(id)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):
    NAME = 'projects'
    IS_COLLECTION = True
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT a.id,
               a.created_at,
               a.created_by,
               a.last_modified_at,
               a.last_modified_by,
               a.namespace_id,
               b.name AS namespace,
               b.slug AS namespace_slug,
               b.icon_class AS namespace_icon,
               a.project_type_id,
               c.name AS project_type,
               c.icon_class AS project_icon,
               a.name,
               a.slug,
               a.description,
               a.configuration_system,
               d.icon_class AS configuration_system_icon,
               a.data_center,
               e.icon_class AS data_center_icon,
               a.deployment_type,
               f.icon_class AS deployment_type_icon,
               a.environments,
               a.orchestration_system,
               g.icon_class AS orchestration_system_icon
          FROM v1.projects AS a
          JOIN v1.namespaces AS b ON b.id = a.namespace_id
          JOIN v1.project_types AS c ON c.id = a.project_type_id
          LEFT JOIN v1.configuration_systems AS d
                 ON d.name = a.configuration_system
          LEFT JOIN v1.data_centers AS e ON e.name = a.data_center
          LEFT JOIN v1.deployment_types AS f ON f.name = a.deployment_type
          LEFT JOIN v1.orchestration_systems AS g
                 ON g.name = a.orchestration_system
          {{WHERE}} {{ORDER_BY}} LIMIT %(limit)s OFFSET %(offset)s""")

    COUNT_SQL = re.sub(r'\s+', ' ', """\
        SELECT count(a.*) AS records
          FROM v1.projects AS a
          JOIN v1.namespaces AS b ON b.id = a.namespace_id
          JOIN v1.project_types AS c ON c.id = a.project_type_id
          {{WHERE}}""")

    FILTER_CHUNKS = {
        'namespace': '(b.name = %(namespace)s OR b.slug = %(namespace)s)',
        'project_type': '(c.name = %(project_type)s '
                        'OR c.slug = %(project_type)s)'
    }

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.projects
                    (namespace_id, project_type_id, created_by,  "name", slug,
                     description, data_center, environments, deployment_type,
                     configuration_system, orchestration_system)
             VALUES (%(namespace_id)s, %(project_type_id)s, %(username)s,
                     %(name)s, %(slug)s, %(description)s, %(data_center)s,
                     %(environments)s, %(deployment_type)s,
                     %(configuration_system)s, %(orchestration_system)s)
          RETURNING id""")

    async def get(self, *args, **kwargs):
        kwargs['limit'] = int(self.get_query_argument('limit', '10'))
        kwargs['offset'] = int(self.get_query_argument('offset', '20'))
        where_chunks = []
        for kwarg in ['namespace', 'project_type', 'name']:
            value = self.get_query_argument(f'where_{kwarg}', None)
            if value is not None:
                kwargs[kwarg] = value
                where_chunks.append(self.FILTER_CHUNKS[kwarg])
        where_sql = ''
        if where_chunks:
            where_sql = ' WHERE {}'.format(' AND '.join(where_chunks))
        sql = self.COLLECTION_SQL.replace('{{WHERE}}', where_sql)
        count_sql = self.COUNT_SQL.replace('{{WHERE}}', where_sql)
        order_by_chunks = []
        for (kwarg, column) in [('namespace', 'b.name'),
                                ('project_type', 'c.name'),
                                ('name', 'a.name')]:
            direction = self.get_query_argument(f'sort_{kwarg}', None)
            if direction in ['asc', 'desc']:
                order_by_chunks.append(
                    '{} {}'.format(column, direction.upper()))
        order_sql = 'ORDER BY a.name ASC'
        if order_by_chunks:
            order_sql = ' ORDER BY {}'.format(', '.join(order_by_chunks))
        sql = sql.replace('{{ORDER_BY}}', order_sql)
        count_sql = count_sql.replace('{{ORDER_BY}}', order_sql)
        count = await self.postgres_execute(
            count_sql, kwargs, metric_name='count-{}'.format(self.NAME))
        result = await self.postgres_execute(
            sql, kwargs, metric_name='get-{}'.format(self.NAME))
        self.send_response({
            'rows': count.row['records'],
            'data': result.rows})


class RecordRequestHandler(_RequestHandlerMixin, base.CRUDRequestHandler):

    NAME = 'project'

    DELETE_SQL = 'DELETE FROM v1.projects WHERE id=%(id)s'

    GET_FULL_SQL = re.sub(r'\s+', ' ', """\
        SELECT a.id,
               a.created_at,
               a.created_by,
               a.last_modified_at,
               a.last_modified_by,
               a.namespace_id,
               b.name AS namespace,
               b.slug AS namespace_slug,
               b.icon_class AS namespace_icon,
               a.project_type_id,
               c.name AS project_type,
               c.slug AS project_type_slug,
               c.icon_class AS project_icon,
               a.name,
               a.slug,
               a.description,
               a.configuration_system,
               d.icon_class AS configuration_system_icon,
               a.data_center,
               e.icon_class AS data_center_icon,
               a.deployment_type,
               f.icon_class AS deployment_type_icon,
               a.environments,
               a.orchestration_system,
               g.icon_class AS orchestration_system_icon
          FROM v1.projects AS a
          JOIN v1.namespaces AS b ON b.id = a.namespace_id
          JOIN v1.project_types AS c ON c.id = a.project_type_id
          LEFT JOIN v1.configuration_systems AS d
                 ON d.name = a.configuration_system
          LEFT JOIN v1.data_centers AS e
                 ON e.name = a.data_center
          LEFT JOIN v1.deployment_types AS f
                 ON f.name = a.deployment_type
          LEFT JOIN v1.orchestration_systems AS g
                 ON g.name = a.orchestration_system
         WHERE a.id=%(id)s""")

    GET_LINKS_SQL = re.sub(r'\s+', ' ', """\
        SELECT b.link_type AS title,
               b.icon_class AS icon,
               a.url AS url
          FROM v1.project_links AS a
          JOIN v1.project_link_types AS b ON b.id = a.link_type_id
         WHERE a.project_id=%(id)s
         ORDER BY b.link_type""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.projects
           SET namespace_id=%(namespace_id)s,
               project_type_id=%(project_type_id)s,
               last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s,
               "name"=%(name)s,
               slug=%(slug)s,
               description=%(description)s,
               data_center=%(data_center)s,
               configuration_system=%(configuration_system)s,
               deployment_type=%(deployment_type)s,
               orchestration_system=%(orchestration_system)s,
               environments=%(environments)s
         WHERE id=%(id)s""")

    async def get(self, *args, **kwargs):
        if self.get_argument('full', 'false') == 'true':
            result = await self.postgres_execute(
                self.GET_FULL_SQL, self._get_query_kwargs(kwargs),
                'get-{}'.format(self.NAME))
            if not result.row_count or not result.row:
                raise web.HTTPError(404, reason='Item not found')
            links_result = await self.postgres_execute(
                self.GET_LINKS_SQL, self._get_query_kwargs(kwargs))
            output = result.row
            output['links'] = links_result.rows
            self.send_response(output)
        else:
            await self._get(kwargs)

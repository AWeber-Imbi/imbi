import asyncio
import re

from imbi import errors, models
from imbi.endpoints import base
from imbi.opensearch import project


class _RequestHandlerMixin:
    ITEM_NAME = 'project'
    ID_KEY = ['id']
    FIELDS = ['id', 'namespace_id', 'project_type_id', 'name', 'slug',
              'description', 'environments', 'archived', 'gitlab_project_id',
              'sentry_project_slug', 'sonarqube_project_key',
              'pagerduty_service_id']
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
               a.environments,
               a.archived,
               a.gitlab_project_id,
               a.sentry_project_slug,
               a.sonarqube_project_key,
               a.pagerduty_service_id
          FROM v1.projects AS a
          JOIN v1.namespaces AS b ON b.id = a.namespace_id
          JOIN v1.project_types AS c ON c.id = a.project_type_id
         WHERE a.id=%(id)s""")


class ProjectAttributeCollectionMixin(project.RequestHandlerMixin):

    async def post(self, *_args, **kwargs):
        result = await self._post(kwargs)
        await self.index_document(result['project_id'])


class ProjectAttributeCRUDMixin(project.RequestHandlerMixin):

    async def delete(self, *args, **kwargs):
        await super().delete(*args, **kwargs)
        await self.index_document(kwargs['project_id'])

    async def patch(self, *args, **kwargs):
        await super().patch(*args, **kwargs)
        await self.index_document(kwargs['project_id'])


class CollectionRequestHandler(project.RequestHandlerMixin,
                               _RequestHandlerMixin,
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
               a.environments,
               a.archived,
               a.gitlab_project_id,
               a.sentry_project_slug,
               a.sonarqube_project_key,
               a.pagerduty_service_id,
               v1.project_score(a.id) AS project_score
          FROM v1.projects AS a
          JOIN v1.namespaces AS b ON b.id = a.namespace_id
          JOIN v1.project_types AS c ON c.id = a.project_type_id
          {{WHERE}} {{ORDER_BY}} LIMIT %(limit)s OFFSET %(offset)s""")

    COUNT_SQL = re.sub(r'\s+', ' ', """\
        SELECT count(a.*) AS records
          FROM v1.projects AS a
          JOIN v1.namespaces AS b ON b.id = a.namespace_id
          JOIN v1.project_types AS c ON c.id = a.project_type_id
          {{WHERE}}""")

    FILTER_CHUNKS = {
        'name': 'to_tsvector(lower(a.name)) @@ websearch_to_tsquery(%(name)s)',
        'namespace_id': 'b.id = %(namespace_id)s',
        'project_type_id': 'c.id = %(project_type_id)s',
        'sonarqube_project_key':
            'a.sonarqube_project_key = %(sonarqube_project_key)s',
    }

    SORT_MAP = {
        'project_score': 'project_score',
        'namespace': 'b.name',
        'project_type': 'c.name',
        'name': 'a.name'
    }

    SORT_PATTERN = re.compile(
        r'(?:(?P<column>name|namespace|project_score|project_type) '
        r'(?P<direction>asc|desc))')

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.projects
                    (namespace_id, project_type_id, created_by,  "name", slug,
                     description, environments)
             VALUES (%(namespace_id)s, %(project_type_id)s, %(username)s,
                     %(name)s, %(slug)s, %(description)s, %(environments)s)
          RETURNING id""")

    async def get(self, *args, **kwargs):
        kwargs['limit'] = int(self.get_query_argument('limit', '10'))
        kwargs['offset'] = int(self.get_query_argument('offset', '0'))
        where_chunks = []
        if self.get_query_argument('include_archived', 'false') == 'false':
            where_chunks.append('a.archived IS FALSE')
        for kwarg in self.FILTER_CHUNKS.keys():
            value = self.get_query_argument(kwarg, None)
            if value is not None:
                kwargs[kwarg] = value
                where_chunks.append(self.FILTER_CHUNKS[kwarg])
        where_sql = ''
        if where_chunks:
            where_sql = ' WHERE {}'.format(' AND '.join(where_chunks))
        sql = self.COLLECTION_SQL.replace('{{WHERE}}', where_sql)
        count_sql = self.COUNT_SQL.replace('{{WHERE}}', where_sql)

        order_sql = 'ORDER BY a.name ASC'
        order_by_chunks = []
        for match in self.SORT_PATTERN.finditer(
                self.get_query_argument('sort', '')):
            order_by_chunks.append(
                f'{match.group("column")} {match.group("direction").upper()}')
        if order_by_chunks:
            order_sql = ' ORDER BY {}'.format(', '.join(order_by_chunks))
        sql = sql.replace('{{ORDER_BY}}', order_sql)

        count = await self.postgres_execute(
            count_sql, kwargs, metric_name='count-{}'.format(self.NAME))
        result = await self.postgres_execute(
            sql, kwargs, metric_name='get-{}'.format(self.NAME))
        self.send_response({
            'rows': count.row['records'],
            'data': result.rows})

    async def post(self, *_args, **kwargs):
        result = await self._post(kwargs)
        await self.index_document(result['id'])


class RecordRequestHandler(project.RequestHandlerMixin,
                           _RequestHandlerMixin,
                           base.CRUDRequestHandler):
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
               a.environments,
               a.archived,
               a.gitlab_project_id,
               a.sentry_project_slug,
               a.sonarqube_project_key,
               a.pagerduty_service_id,
               v1.project_score(a.id)
          FROM v1.projects AS a
          JOIN v1.namespaces AS b ON b.id = a.namespace_id
          JOIN v1.project_types AS c ON c.id = a.project_type_id
         WHERE a.id=%(id)s""")

    GET_FACTS_SQL = re.sub(r'\s+', ' ', """\
        WITH project_type_id AS (SELECT project_type_id AS id
                                   FROM v1.projects
                                  WHERE id = %(id)s)
        SELECT a.id AS fact_type_id,
               a.name,
               b.recorded_at,
               b.recorded_by,
               CASE WHEN a.data_type = 'boolean' THEN b.value::bool::text
                    WHEN a.data_type = 'date' THEN b.value::date::text
                    WHEN a.data_type = 'decimal'
                         THEN b.value::numeric(9,2)::text
                    WHEN a.data_type = 'integer'
                         THEN b.value::integer::text
                    WHEN a.data_type = 'timestamp'
                         THEN b.value::timestamptz::text
                    ELSE b.value
                END AS value,
               a.data_type,
               a.fact_type,
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
                              WHEN a.data_type = 'boolean'
                               AND b.value = 'true' THEN 100
                              ELSE 0
                          END
                END AS score,
               CASE WHEN a.fact_type = 'enum' THEN (
                              SELECT icon_class
                                FROM v1.project_fact_type_enums
                               WHERE fact_type_id = b.fact_type_id
                                 AND value = b.value)
                    ELSE NULL
                END AS icon_class
          FROM v1.project_fact_types AS a
     LEFT JOIN v1.project_facts AS b
            ON b.fact_type_id = a.id
           AND b.project_id = %(id)s
         WHERE (SELECT id FROM project_type_id) = ANY(a.project_type_ids)
        ORDER BY a.name""")

    GET_LINKS_SQL = re.sub(r'\s+', ' ', """\
        SELECT a.link_type_id,
               b.link_type AS title,
               b.icon_class AS icon,
               a.url AS url
          FROM v1.project_links AS a
          JOIN v1.project_link_types AS b ON b.id = a.link_type_id
         WHERE a.project_id=%(id)s
         ORDER BY b.link_type""")

    GET_URLS_SQL = re.sub(r'\s+', ' ', """\
        SELECT environment, url
          FROM v1.project_urls
         WHERE project_id=%(id)s
         ORDER BY environment""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.projects
           SET namespace_id=%(namespace_id)s,
               project_type_id=%(project_type_id)s,
               last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s,
               "name"=%(name)s,
               slug=%(slug)s,
               description=%(description)s,
               environments=%(environments)s,
               archived=%(archived)s,
               gitlab_project_id=%(gitlab_project_id)s,
               sentry_project_slug=%(sentry_project_slug)s,
               sonarqube_project_key=%(sonarqube_project_key)s,
               pagerduty_service_id=%(pagerduty_service_id)s
         WHERE id=%(id)s""")

    async def delete(self, *args, **kwargs):
        await super().delete(*args, **kwargs)
        await self.search_index.delete_document(kwargs['id'])

    async def get(self, *args, **kwargs):
        if self.get_argument('full', 'false') == 'true':
            query_args = self._get_query_kwargs(kwargs)
            project, facts, links, urls = await asyncio.gather(
                self.postgres_execute(
                    self.GET_FULL_SQL, query_args, 'get-{}'.format(self.NAME)),
                self.postgres_execute(
                    self.GET_FACTS_SQL, query_args, 'get-project-facts'),
                self.postgres_execute(
                    self.GET_LINKS_SQL, query_args, 'get-project-links'),
                self.postgres_execute(
                    self.GET_URLS_SQL, query_args, 'get-project-urls'))

            if not project.row_count or not project.row:
                raise errors.ItemNotFound()

            output = project.row
            output.update({
                'facts': facts.rows,
                'links': links.rows,
                'urls': {row['environment']: row['url'] for row in urls.rows}
            })
            self.send_response(output)
        else:
            await self._get(kwargs)

    async def patch(self, *args, **kwargs):
        await super().patch(*args, **kwargs)
        await self.index_document(kwargs['id'])


class SearchRequestHandler(project.RequestHandlerMixin,
                           base.AuthenticatedRequestHandler):

    async def get(self):
        result = await self.search_index.search(self.get_query_argument('s'))
        self.send_response(result)


class SearchIndexRequestHandler(project.RequestHandlerMixin,
                                base.ValidatingRequestHandler):
    SQL = re.sub(r'\s+', ' ', """\
        SELECT id
          FROM v1.projects
         ORDER BY id""")

    async def post(self):
        result = await self.postgres_execute(self.SQL)
        for row in result:
            value = await models.project(row['id'], self.application)
            await self.search_index.index_document(value)

        self.send_response({
            'status': 'ok',
            'message': f'Queued {len(result)} projects for indexing'})

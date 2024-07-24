import re

from imbi.endpoints import base, projects


class _DependencyRequestMixin:

    ID_KEY = ['project_id', 'dependency_id']
    ITEM_NAME = 'project-dependency'
    FIELDS = ['project_id', 'dependency_id']
    TTL = 300

    GET_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT project_id, created_at, created_by, dependency_id
          FROM v1.project_dependencies
         WHERE project_id=%(project_id)s
           AND dependency_id=%(dependency_id)s""")


class CollectionRequestHandler(projects.ProjectAttributeCollectionMixin,
                               _DependencyRequestMixin,
                               base.CollectionRequestHandler):

    NAME = 'project-dependencies'

    COLLECTION_SQL = re.sub(
        r'\s+', ' ', """\
          SELECT project_id, created_by, dependency_id
            FROM v1.project_dependencies
           WHERE project_id=%(project_id)s
        ORDER BY dependency_id""")

    COLLECTION_WITH_DEPENDENCY_SQL = re.sub(
        r'\s+', ' ', """\
        SELECT d.project_id, d.created_at, d.created_by, d.dependency_id,
               p.name AS dependency_name,
               p.namespace_id AS dependency_namespace_id,
               p.project_type_id AS dependency_project_type_id
          FROM v1.project_dependencies AS d
          JOIN v1.projects AS p
            ON d.dependency_id=p.id
         WHERE project_id=%(project_id)s""")

    POST_SQL = re.sub(
        r'\s+', ' ', """\
        INSERT INTO v1.project_dependencies
                    (project_id, dependency_id, created_by)
             VALUES (%(project_id)s, %(dependency_id)s, %(username)s)
          RETURNING project_id, dependency_id""")

    async def get(self, *args, **kwargs):
        if 'dependency' in self.get_query_arguments('include'):
            result = await self.postgres_execute(
                self.COLLECTION_WITH_DEPENDENCY_SQL,
                kwargs,
                metric_name='get-{}'.format(self.NAME))
            response = [{
                'project_id': row['project_id'],
                'dependency_id': row['dependency_id'],
                'created_at': row['created_at'],
                'created_by': row['created_by'],
                'dependency': {
                    'id': row['dependency_id'],
                    'name': row['dependency_name'],
                    'namespace_id': row['dependency_namespace_id'],
                    'project_type_id': row['dependency_project_type_id'],
                }
            } for row in result.rows]
            self.send_response(response)
        else:
            await super().get(*args, **kwargs)


class RecordRequestHandler(projects.ProjectAttributeCRUDMixin,
                           _DependencyRequestMixin, base.CRUDRequestHandler):

    NAME = 'project-dependency'

    DELETE_SQL = re.sub(
        r'\s+', ' ', """\
        DELETE FROM v1.project_dependencies
         WHERE project_id=%(project_id)s
           AND dependency_id=%(dependency_id)s""")

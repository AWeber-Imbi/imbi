import re

from imbi.endpoints import base, projects


class _DependencyRequestMixin:

    ID_KEY = ['project_id', 'dependency_id']
    ITEM_NAME = 'project-dependency'
    FIELDS = ['project_id', 'dependency_id']
    TTL = 300

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT project_id, created_at, created_by, dependency_id
          FROM v1.project_dependencies
         WHERE project_id=%(project_id)s
           AND dependency_id=%(dependency_id)s""")


class CollectionRequestHandler(projects.ProjectAttributeCollectionMixin,
                               _DependencyRequestMixin,
                               base.CollectionRequestHandler):

    NAME = 'project-dependencies'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
          SELECT project_id, created_by, dependency_id
            FROM v1.project_dependencies
           WHERE project_id=%(project_id)s
        ORDER BY dependency_id""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.project_dependencies
                    (project_id, dependency_id, created_by)
             VALUES (%(project_id)s, %(dependency_id)s, %(username)s)
          RETURNING project_id, dependency_id""")


class RecordRequestHandler(projects.ProjectAttributeCRUDMixin,
                           _DependencyRequestMixin, base.CRUDRequestHandler):

    NAME = 'project-dependency'

    DELETE_SQL = re.sub(r'\s+', ' ', """\
        DELETE FROM v1.project_dependencies
         WHERE project_id=%(project_id)s
           AND dependency_id=%(dependency_id)s""")

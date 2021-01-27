import re

from imbi.endpoints import base


class _DependencyRequestMixin:

    ID_KEY = ['name', 'namespace', 'dependency_name', 'dependency_namespace']
    ITEM_NAME = 'project-dependency'
    FIELDS = ['name', 'namespace', 'dependency_name', 'dependency_namespace']
    TTL = 300

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT namespace, name, dependency_namespace, dependency_name,
           created_at, created_by
      FROM v1.project_dependencies
     WHERE namespace=%(namespace)s
       AND name=%(name)s
       AND dependency_namespace=%(dependency_namespace)s
       AND dependency_name=%(dependency_name)s""")


class CollectionRequestHandler(_DependencyRequestMixin,
                               base.CollectionRequestHandler):

    NAME = 'project-dependencies'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
      SELECT dependency_namespace, dependency_name
        FROM v1.project_dependencies
       WHERE namespace=%(namespace)s
         AND name=%(name)s
    ORDER BY namespace, name, dependency_namespace, dependency_name""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.project_dependencies
                (namespace, name, dependency_namespace, dependency_name,
                 created_by)
         VALUES (%(namespace)s, %(name)s, %(dependency_namespace)s,
                 %(dependency_name)s, %(username)s)
      RETURNING namespace, name, dependency_namespace, dependency_name;""")


class RecordRequestHandler(_DependencyRequestMixin, base.CRUDRequestHandler):

    NAME = 'project-dependency'

    DELETE_SQL = re.sub(r'\s+', ' ', """\
    DELETE FROM v1.project_dependencies
     WHERE namespace=%(namespace)s
       AND name=%(name)s
       AND dependency_namespace=%(dependency_namespace)s
       AND dependency_name=%(dependency_name)s""")

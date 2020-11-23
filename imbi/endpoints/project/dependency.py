"""
Request Handler for an individual project

"""
from imbi.endpoints import base


class RequestHandler(base.CRUDRequestHandler):

    NAME = 'project-dependency'
    ITEM_SCHEMA = 'project/dependency.yaml'
    ID_KEY = ['project_id', 'dependency_id']
    FIELDS = ['project_id', 'dependency_id']
    TTL = 300

    DELETE_SQL = """\
    DELETE FROM v1.project_dependencies
          WHERE project_id=%(project_id)s
            AND dependency_id=%(dependency_id)s"""

    GET_SQL = """\
    SELECT project_id, created_at, dependency_id
      FROM v1.project_dependencies
     WHERE project_id=%(project_id)s
       AND dependency_id=%(dependency_id)s"""

    POST_SQL = """\
    INSERT INTO v1.project_dependencies (project_id, dependency_id)
         VALUES (%(project_id)s, %(dependency_id)s)
      RETURNING project_id, dependency_id;"""

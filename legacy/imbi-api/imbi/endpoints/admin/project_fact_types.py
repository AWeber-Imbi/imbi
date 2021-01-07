from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-project-fact-types'
    ID_KEY = 'id'
    ITEM_SCHEMA = 'admin/project_fact_type.yaml'
    FIELDS = ['id', 'project_type', 'name', 'weight']

    DELETE_SQL = 'DELETE FROM v1.project_fact_types WHERE id=%(id)s;'

    GET_SQL = """\
    SELECT id, created_at, modified_at, project_type, "name", weight
      FROM v1.project_fact_types
     WHERE id=%(id)s;"""

    PATCH_SQL = """\
    UPDATE v1.project_fact_types
       SET id=%(id)s,
           modified_at=CURRENT_TIMESTAMP,
           project_type=%(project_type)s,
           "name"=%(name)s,
           weight=%(weight)s
     WHERE "id"=%(id)s;"""

    POST_SQL = """\
    INSERT INTO v1.project_fact_types (id, project_type, "name", weight)
         VALUES (%(id)s, %(project_type)s, %(name)s, %(weight)s)
      RETURNING id;"""

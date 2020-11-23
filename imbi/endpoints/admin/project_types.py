"""
Request Handlers for the Environments Endpoints

"""
from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-project-types'
    ID_KEY = 'name'
    ITEM_SCHEMA = 'admin/project_type.yaml'
    FIELDS = ['name', 'description', 'icon_class']
    DEFAULTS = {'icon_class': 'fas fa-mountain'}

    DELETE_SQL = 'DELETE FROM v1.project_types WHERE "name"=%(name)s;'

    GET_SQL = """\
    SELECT "name", created_at, modified_at, description, slug, icon_class
      FROM v1.project_types
     WHERE "name"=%(name)s;"""

    PATCH_SQL = """\
    UPDATE v1.project_types
       SET "name"=%(name)s,
           modified_at=CURRENT_TIMESTAMP,
           description=%(description)s,
           slug=%(slug)s,
           icon_class=%(icon_class)s
     WHERE "name"=%(name)s;"""

    POST_SQL = """\
    INSERT INTO v1.project_types ("name", description, slug, icon_class)
         VALUES (%(name)s, %(description)s, %(slug)s, %(icon_class)s)
      RETURNING "name";"""

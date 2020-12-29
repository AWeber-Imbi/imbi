from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-cookie-cutters'
    ID_KEY = 'name'
    ITEM_SCHEMA = 'admin/cookie_cutter.yaml'
    FIELDS = ['name', 'description', 'type', 'project_type', 'url']

    DELETE_SQL = 'DELETE FROM v1.cookie_cutters WHERE "name"=%(name)s;'

    GET_SQL = """\
    SELECT "name", created_at, modified_at, description, "type",
           project_type, url
      FROM v1.cookie_cutters
     WHERE "name"=%(name)s;"""

    PATCH_SQL = """\
    UPDATE v1.cookie_cutters
       SET "name"=%(name)s,
           modified_at=CURRENT_TIMESTAMP,
           description=%(description)s,
           "type"=%(type)s,
           project_type=%(project_type)s,
           url=%(url)s
     WHERE "name"=%(current_name)s;"""

    POST_SQL = """\
    INSERT INTO v1.cookie_cutters ("name", project_type, "type",
                                   description, url)
         VALUES (%(name)s, %(project_type)s, %(type)s,
                 %(description)s, %(url)s)
      RETURNING "name";"""

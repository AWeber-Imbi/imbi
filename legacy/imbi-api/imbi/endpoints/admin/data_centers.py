from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-data-centers'
    ID_KEY = 'name'
    ITEM_SCHEMA = 'admin/data_center.yaml'
    FIELDS = ['name', 'description', 'icon_class']
    DEFAULTS = {'icon_class': 'fas fa-building'}

    DELETE_SQL = 'DELETE FROM v1.data_centers WHERE "name"=%(name)s;'

    GET_SQL = """\
    SELECT "name", created_at, modified_at, description, icon_class
      FROM v1.data_centers
     WHERE "name"=%(name)s;"""

    PATCH_SQL = """\
    UPDATE v1.data_centers
       SET "name"=%(name)s,
           modified_at=CURRENT_TIMESTAMP,
           description=%(description)s,
           icon_class=%(icon_class)s
     WHERE "name"=%(current_name)s;"""

    POST_SQL = """\
    INSERT INTO v1.data_centers ("name", description, icon_class)
         VALUES (%(name)s, %(description)s, %(icon_class)s)
      RETURNING "name";"""

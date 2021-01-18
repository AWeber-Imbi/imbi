import re

from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-environments'
    ID_KEY = 'name'
    ITEM_SCHEMA = 'admin/environment.yaml'
    FIELDS = ['name', 'description', 'text_class', 'icon_class']
    DEFAULTS = {'icon_class': 'fas fa-mountain'}

    DELETE_SQL = 'DELETE FROM v1.environments WHERE "name"=%(name)s;'

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT "name", created_at, modified_at, description, icon_class, text_class
      FROM v1.environments
     WHERE "name"=%(name)s;""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
    UPDATE v1.environments
       SET "name"=%(name)s,
           modified_at=CURRENT_TIMESTAMP,
           description=%(description)s,
           icon_class=%(icon_class)s,
           text_class=%(text_class)s
     WHERE "name"=%(current_name)s;""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.environments ("name", description, icon_class, text_class)
         VALUES (%(name)s, %(description)s, %(icon_class)s, %(text_class)s)
      RETURNING "name";""")

import re

from imbi.endpoints import base


class AdminCRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-orchestration-systems'
    ID_KEY = 'name'
    FIELDS = ['name', 'description', 'icon_class']
    DEFAULTS = {'icon_class': 'fas fa-hand-point-right'}

    DELETE_SQL = re.sub(r'\s+', ' ', """\
    DELETE FROM v1.orchestration_systems WHERE "name"=%(name)s;""")

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT "name", created_at, created_by, last_modified_at, last_modified_by,
           description, icon_class
      FROM v1.orchestration_systems
     WHERE "name"=%(name)s;""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
    UPDATE v1.orchestration_systems
       SET "name"=%(name)s,
           last_modified_at=CURRENT_TIMESTAMP,
           last_modified_by=%(username)s,
           description=%(description)s,
           icon_class=%(icon_class)s
     WHERE "name"=%(current_name)s;""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.orchestration_systems
                ("name", created_by, description, icon_class)
         VALUES (%(name)s, %(username)s, %(description)s, %(icon_class)s)
      RETURNING "name";""")

import re

from imbi.endpoints import base


class AdminCRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-cookie-cutters'
    ID_KEY = 'name'
    FIELDS = ['name', 'description', 'type', 'project_type', 'url']

    DELETE_SQL = 'DELETE FROM v1.cookie_cutters WHERE "name"=%(name)s;'

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT "name", created_at, created_by, last_modified_at, last_modified_by,
           description, "type", project_type_id, url
      FROM v1.cookie_cutters
     WHERE "name"=%(name)s;""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
    UPDATE v1.cookie_cutters
       SET "name"=%(name)s,
           last_modified_at=CURRENT_TIMESTAMP,
           last_modified_by=%(username)s,
           description=%(description)s,
           "type"=%(type)s,
           project_type_id=%(project_type_id)s,
           url=%(url)s
     WHERE "name"=%(current_name)s;""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.cookie_cutters ("name", created_by, project_type_id, "type",
                                   description, url)
         VALUES (%(name)s, %(username)s, %(project_type_id)s, %(type)s,
                 %(description)s, %(url)s)
      RETURNING "name";""")

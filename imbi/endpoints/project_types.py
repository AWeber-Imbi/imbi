import re

from imbi.endpoints import base


class AdminCRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'project-types'
    ID_KEY = 'id'
    FIELDS = ['id', 'name', 'description', 'icon_class']
    DEFAULTS = {'icon_class': 'fas fa-folder'}

    DELETE_SQL = 'DELETE FROM v1.project_types WHERE id=%(id)s;'

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT id, "name", created_at, created_by,
           last_modified_at, last_modified_by,
           description, slug, icon_class
      FROM v1.project_types
     WHERE id=%(id)s;""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
    UPDATE v1.project_types
       SET "name"=%(name)s,
           last_modified_at=CURRENT_TIMESTAMP,
           last_modified_by=%(username)s,
           description=%(description)s,
           slug=%(slug)s,
           icon_class=%(icon_class)s
     WHERE id=%(id)s;""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.project_types
                ("name", created_by, description, slug, icon_class)
         VALUES (%(name)s, %(username)s, %(description)s, %(slug)s,
                 %(icon_class)s)
      RETURNING id;""")

import re

from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-namespaces'
    ID_KEY = 'id'
    FIELDS = ['id', 'name', 'slug', 'icon_class', 'maintained_by']
    DEFAULTS = {'icon_class': 'fas fa-users', 'maintained_by': []}

    DELETE_SQL = 'DELETE FROM v1.namespaces WHERE id=%(id)s;'

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT id, "name", created_at, created_by,
           last_modified_at, last_modified_by,
           slug, icon_class, maintained_by
      FROM v1.namespaces WHERE id=%(id)s;""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
    UPDATE v1.namespaces
       SET "name" = %(name)s,
           last_modified_at = CURRENT_TIMESTAMP,
           last_modified_by = %(username)s,
           slug = %(slug)s,
           icon_class = %(icon_class)s,
           "maintained_by" = %(maintained_by)s
     WHERE id=%(id)s;""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.namespaces
                ("name", created_by, slug, icon_class, "maintained_by")
         VALUES (%(name)s, %(username)s, %(slug)s, %(icon_class)s,
                 %(maintained_by)s)
      RETURNING id;""")

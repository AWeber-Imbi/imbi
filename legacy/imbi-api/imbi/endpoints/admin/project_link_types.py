import re

from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-project-link-types'
    ID_KEY = 'link_type'
    FIELDS = ['link_type', 'icon_class']
    DEFAULTS = {'icon_class': 'fas fa-link'}

    DELETE_SQL = re.sub(r'\s+', ' ', """\
    DELETE FROM v1.project_link_types WHERE link_type=%(link_type)s;""")

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT link_type, created_at, created_by, last_modified_at,
           last_modified_by, icon_class
      FROM v1.project_link_types
     WHERE link_type=%(link_type)s;""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
    UPDATE v1.project_link_types
       SET link_type=%(link_type)s,
           last_modified_at=CURRENT_TIMESTAMP,
           last_modified_by=%(username)s,
           icon_class=%(icon_class)s
     WHERE link_type=%(current_link_type)s;""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.project_link_types (link_type, created_by, icon_class)
         VALUES (%(link_type)s, %(username)s, %(icon_class)s)
      RETURNING link_type""")

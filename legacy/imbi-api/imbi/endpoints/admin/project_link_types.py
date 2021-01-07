from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-project-link-types'
    ID_KEY = 'link_type'
    ITEM_SCHEMA = 'admin/project_link_type.yaml'
    FIELDS = ['link_type', 'icon_class']
    DEFAULTS = {'icon_class': 'fas fa-link'}

    DELETE_SQL = """\
    DELETE FROM v1.project_link_types WHERE link_type=%(link_type)s;"""

    GET_SQL = """\
    SELECT link_type, created_at, modified_at, icon_class
      FROM v1.project_link_types
     WHERE link_type=%(link_type)s;"""

    PATCH_SQL = """\
    UPDATE v1.project_link_types
       SET modified_at=CURRENT_TIMESTAMP,
           icon_class=%(icon_class)s
     WHERE link_type=%(current_link_type)s;"""

    POST_SQL = """\
    INSERT INTO v1.project_link_types (link_type, icon_class)
         VALUES (%(link_type)s, %(icon_class)s)
      RETURNING link_type"""

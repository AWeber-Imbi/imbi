import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ID_KEY = 'id'
    FIELDS = ['id', 'link_type', 'icon_class']
    DEFAULTS = {'icon_class': 'fas fa-link'}

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, created_at, created_by, last_modified_at, last_modified_by,
               link_type, icon_class
          FROM v1.project_link_types
         WHERE id=%(id)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):

    NAME = 'project-link-types'
    ITEM_NAME = 'project-link-type'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, link_type, icon_class
          FROM v1.project_link_types
         ORDER BY link_type ASC""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.project_link_types
                    (link_type, created_by, icon_class)
             VALUES (%(link_type)s, %(username)s, %(icon_class)s)
          RETURNING id""")


class RecordRequestHandler(_RequestHandlerMixin, base.AdminCRUDRequestHandler):

    NAME = 'project-link-type'

    DELETE_SQL = 'DELETE FROM v1.project_link_types WHERE id=%(id)s'

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.project_link_types
           SET link_type=%(link_type)s,
               last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s,
               icon_class=%(icon_class)s
         WHERE id=%(id)s""")

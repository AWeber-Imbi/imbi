import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ID_KEY = 'name'
    FIELDS = ['name', 'group_type', 'external_id', 'permissions']
    DEFAULTS = {'group_type': 'internal', 'permissions': []}

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT "name", created_at, created_by,
               last_modified_at, last_modified_by,
               group_type, external_id, permissions
          FROM v1.groups
         WHERE "name"=%(name)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):

    NAME = 'groups'
    ITEM_NAME = 'group'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT "name", group_type, external_id, permissions
          FROM v1.groups
         ORDER BY "name" ASC""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.groups
                    ("name", created_by, group_type, external_id, permissions)
             VALUES (%(name)s, %(username)s, %(group_type)s, %(external_id)s,
                     %(permissions)s)
          RETURNING "name";""")


class RecordRequestHandler(_RequestHandlerMixin, base.AdminCRUDRequestHandler):

    NAME = 'group'

    DELETE_SQL = 'DELETE FROM v1.groups WHERE "name"=%(name)s;'

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.groups
           SET "name"=%(name)s,
               last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s,
               group_type=%(group_type)s,
               external_id=%(external_id)s,
               permissions=%(permissions)s
         WHERE "name"=%(current_name)s""")

"""
Request Handlers for the Groups Endpoints

"""
from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-groups'
    ID_KEY = 'name'
    ITEM_SCHEMA = 'admin/group.yaml'
    FIELDS = ['name', 'group_type', 'external_id', 'permissions']
    DEFAULTS = {'group_type': 'internal', 'permissions': []}

    DELETE_SQL = 'DELETE FROM v1.groups WHERE "name"=%(name)s;'

    GET_SQL = """\
    SELECT "name", created_at, modified_at, group_type,
           external_id, permissions
      FROM v1.groups
     WHERE "name"=%(name)s;"""

    PATCH_SQL = """\
    UPDATE v1.groups
       SET "name"=%(name)s,
           modified_at=CURRENT_TIMESTAMP,
           group_type=%(group_type)s,
           external_id=%(external_id)s,
           permissions=%(permissions)s
     WHERE "name"=%(current_name)s;"""

    POST_SQL = """\
    INSERT INTO v1.groups ("name", group_type, external_id, permissions)
         VALUES (%(name)s, %(group_type)s, %(external_id)s, %(permissions)s)
      RETURNING "name";"""

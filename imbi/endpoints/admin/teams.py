"""
Request Handlers for the Teams Endpoints

"""
from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-teams'
    ID_KEY = 'name'
    ITEM_SCHEMA = 'admin/team.yaml'
    FIELDS = ['name', 'slug', 'icon_class', 'group']
    DEFAULTS = {'icon_class': 'fas fa-users', 'group': None}

    DELETE_SQL = 'DELETE FROM v1.teams WHERE "name"=%(name)s;'

    GET_SQL = """\
    SELECT "name", created_at, modified_at, slug, icon_class, "group"
      FROM v1.teams WHERE "name"=%(name)s;"""

    PATCH_SQL = """\
    UPDATE v1.teams
       SET "name" = %(name)s,
           modified_at = CURRENT_TIMESTAMP,
           slug = %(slug)s,
           icon_class = %(icon_class)s,
           "group" = %(group)s
     WHERE "name"=%(current_name)s;"""

    POST_SQL = """\
    INSERT INTO v1.teams ("name", slug, icon_class, "group")
         VALUES (%(name)s, %(slug)s, %(icon_class)s, %(group)s)
      RETURNING "name";"""

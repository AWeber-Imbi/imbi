"""
Request Handlers for the Configuration System Endpoints

"""
from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-configuration-systems'
    ID_KEY = 'name'
    ITEM_SCHEMA = 'admin/configuration_system.yaml'
    FIELDS = ['name', 'description', 'icon_class']
    DEFAULTS = {'icon_class': 'fas fa-globe'}

    DELETE_SQL = 'DELETE FROM v1.configuration_systems WHERE "name"=%(name)s;'

    GET_SQL = """\
    SELECT "name", created_at, modified_at, description, icon_class
      FROM v1.configuration_systems
     WHERE "name"=%(name)s;"""

    PATCH_SQL = """\
    UPDATE v1.configuration_systems
       SET "name"=%(name)s,
           modified_at=CURRENT_TIMESTAMP,
           description=%(description)s,
           icon_class=%(icon_class)s
     WHERE "name"=%(current_name)s;"""

    POST_SQL = """\
    INSERT INTO v1.configuration_systems ("name", description, icon_class)
         VALUES (%(name)s, %(description)s, %(icon_class)s)
      RETURNING "name";"""

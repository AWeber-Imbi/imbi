import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ITEM_NAME = 'configuration-system'
    ID_KEY = 'name'
    FIELDS = ['name', 'description', 'icon_class']
    DEFAULTS = {'icon_class': 'fas fa-globe'}
    TTL = 300

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT "name", created_at, created_by,
               last_modified_at, last_modified_by,
               description, icon_class
          FROM v1.configuration_systems
         WHERE "name"=%(name)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):

    NAME = 'configuration-systems'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT "name", created_by, last_modified_by, description, icon_class
          FROM v1.configuration_systems
         ORDER BY "name" ASC""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.configuration_systems
                    ("name", created_by, description, icon_class)
             VALUES (%(name)s, %(username)s, %(description)s, %(icon_class)s)
          RETURNING "name";""")


class RecordRequestHandler(_RequestHandlerMixin, base.AdminCRUDRequestHandler):

    NAME = 'configuration-system'

    DELETE_SQL = 'DELETE FROM v1.configuration_systems WHERE "name"=%(name)s'

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.configuration_systems
           SET "name"=%(name)s,
               last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s,
               description=%(description)s,
               icon_class=%(icon_class)s
         WHERE "name"=%(current_name)s""")

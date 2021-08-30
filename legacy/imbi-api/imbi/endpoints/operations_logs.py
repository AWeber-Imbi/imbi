import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ID_KEY = 'id'
    FIELDS = ['id', 'recorded_at', 'recorded_by', 'completed_at', 'project_id',
              'environment', 'change_type', 'description', 'link', 'notes',
              'ticket_slug', 'version']

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, recorded_at, recorded_by, completed_at,
               project_id, environment, change_type, description,
               link, notes, ticket_slug, "version"
          FROM v1.operations_log
         WHERE id = %(id)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):

    NAME = 'operations-logs'
    ITEM_NAME = 'operations-log'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, recorded_at, recorded_by, completed_at,
               project_id, environment, change_type, description,
               link, notes, ticket_slug, "version"
          FROM v1.operations_log
         ORDER BY id ASC""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.operations_log
                    (recorded_by, recorded_at, completed_at,
                     project_id, environment, change_type, description,
                     link, notes, ticket_slug, "version")
             VALUES (%(recorded_by)s, %(recorded_at)s, %(completed_at)s,
                     %(project_id)s, %(environment)s, %(change_type)s,
                     %(description)s, %(link)s, %(notes)s, %(ticket_slug)s,
                     %(version)s)
          RETURNING id""")


class RecordRequestHandler(_RequestHandlerMixin,
                           base.AdminCRUDRequestHandler):
    NAME = 'operations-log'

    DELETE_SQL = 'DELETE FROM v1.operations_log WHERE id = %(id)s;'

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.operations_log
           SET recorded_by = %(recorded_by)s,
               recorded_at = %(recorded_at)s,
               completed_at = %(completed_at)s,
               project_id = %(project_id)s,
               environment = %(environment)s,
               change_type = %(change_type)s,
               description = %(description)s,
               link = %(link)s,
               notes = %(notes)s,
               ticket_slug = %(ticket_slug)s,
               "version" = %(version)s
         WHERE id = %(id)s""")

import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ID_KEY = ['id']
    FIELDS = ['id', 'project_type_id', 'fact_type', 'weight']

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, created_at, created_by,
               last_modified_at, last_modified_by,
               project_type_id, fact_type, weight
          FROM v1.project_fact_types
         WHERE id=%(id)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):

    NAME = 'project-fact-types'
    ITEM_NAME = 'project-fact-type'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, project_type_id, fact_type, weight
          FROM v1.project_fact_types
         ORDER BY id""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.project_fact_types
                    (project_type_id, fact_type, created_by, weight)
             VALUES (%(project_type_id)s, %(fact_type)s, %(username)s,
                     %(weight)s)
          RETURNING id""")


class RecordRequestHandler(_RequestHandlerMixin, base.AdminCRUDRequestHandler):

    NAME = 'project-fact-type'

    DELETE_SQL = 'DELETE FROM v1.project_fact_types WHERE id=%(id)s'

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.project_fact_types
           SET project_type_id=%(project_type_id)s,
               fact_type=%(fact_type)s,
               last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s,
               weight=%(weight)s
         WHERE id=%(id)s""")

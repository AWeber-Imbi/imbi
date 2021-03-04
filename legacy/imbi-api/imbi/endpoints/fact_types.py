import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ID_KEY = ['id']
    FIELDS = ['id', 'project_type_ids', 'name', 'fact_type', 'data_type',
              'description', 'ui_options', 'weight']
    DEFAULTS = {
        'data_type': 'string',
        'fact_type': 'free-form',
        'weight': 0
    }

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, created_at, created_by, last_modified_at, last_modified_by,
               project_type_ids, name, fact_type, data_type, description,
               ui_options, weight
          FROM v1.project_fact_types
         WHERE id=%(id)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):

    NAME = 'fact-types'
    ITEM_NAME = 'fact-type'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, project_type_ids, name, fact_type, data_type, description,
               ui_options, weight
          FROM v1.project_fact_types
         ORDER BY name, project_type_ids""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.project_fact_types
                    (project_type_ids, created_by, name, fact_type, data_type,
                     description, ui_options, weight)
             VALUES (%(project_type_ids)s, %(username)s, %(name)s,
                     %(fact_type)s, %(data_type)s, %(description)s,
                     %(ui_options)s, %(weight)s)
          RETURNING id""")


class RecordRequestHandler(_RequestHandlerMixin, base.AdminCRUDRequestHandler):

    NAME = 'fact-type'

    DELETE_SQL = 'DELETE FROM v1.project_fact_types WHERE id=%(id)s'

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.project_fact_types
           SET last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s,
               project_type_ids=%(project_type_ids)s,
               name=%(name)s,
               fact_type=%(fact_type)s,
               data_type=%(data_type)s,
               description=%(description)s,
               ui_options=%(ui_options)s,
               weight=%(weight)s
         WHERE id=%(id)s""")

import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ID_KEY = ['id']
    FIELDS = ['id', 'fact_type_id', 'min_value', 'max_value',  'score']

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, fact_type_id, created_at, created_by,
               last_modified_at, last_modified_by, min_value, max_value, score
          FROM v1.project_fact_type_ranges
         WHERE id=%(id)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):

    NAME = 'fact-type-ranges'
    ITEM_NAME = 'fact-type-range'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, fact_type_id, min_value, max_value, score
          FROM v1.project_fact_type_ranges
      ORDER BY id""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.project_fact_type_ranges
                    (fact_type_id, created_by, min_value, max_value, score)
             VALUES (%(fact_type_id)s,  %(username)s, %(min_value)s,
                     %(max_value)s, %(score)s)
          RETURNING id""")


class RecordRequestHandler(_RequestHandlerMixin, base.AdminCRUDRequestHandler):

    NAME = 'fact-type-range'

    DELETE_SQL = 'DELETE FROM v1.project_fact_type_ranges WHERE id=%(id)s'

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.project_fact_type_ranges
           SET fact_type_id=%(fact_type_id)s,
               last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s,
               min_value=%(min_value)s,
               max_value=%(max_value)s,
               score=%(score)s
         WHERE id=%(id)s""")

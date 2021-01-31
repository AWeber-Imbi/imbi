import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ID_KEY = ['id']
    FIELDS = ['id', 'fact_type_id', 'value', 'score']

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, fact_type_id, created_at, created_by,
               last_modified_at, last_modified_by, value, score
          FROM v1.project_fact_type_options
         WHERE id=%(id)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):

    NAME = 'project-fact-type-options'
    ITEM_NAME = 'project-fact-type-option'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, fact_type_id, value, score
          FROM v1.project_fact_type_options
      ORDER BY id""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.project_fact_type_options
                    (fact_type_id, value, created_by, score)
             VALUES (%(fact_type_id)s, %(value)s, %(username)s, %(score)s)
          RETURNING id""")


class RecordRequestHandler(_RequestHandlerMixin, base.AdminCRUDRequestHandler):

    NAME = 'project-fact-type-option'

    DELETE_SQL = 'DELETE FROM v1.project_fact_type_options WHERE id=%(id)s'

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.project_fact_type_options
           SET fact_type_id=%(fact_type_id)s,
               last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s,
               value=%(value)s,
               score=%(score)s
         WHERE id=%(id)s""")

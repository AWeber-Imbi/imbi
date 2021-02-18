import re

from imbi.endpoints import base


class _RequestHandlerMixin:

    ID_KEY = ['id']
    FIELDS = ['id', 'fact_type_id', 'value', 'icon_class',  'score']

    GET_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, fact_type_id, created_at, created_by,
               last_modified_at, last_modified_by, value, icon_class, score
          FROM v1.project_fact_type_enums
         WHERE id=%(id)s""")


class CollectionRequestHandler(_RequestHandlerMixin,
                               base.CollectionRequestHandler):

    NAME = 'project-fact-type-enums'
    ITEM_NAME = 'project-fact-type-enum'

    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT id, fact_type_id, value, icon_class, score
          FROM v1.project_fact_type_enums
      ORDER BY id""")

    POST_SQL = re.sub(r'\s+', ' ', """\
        INSERT INTO v1.project_fact_type_enums
                    (fact_type_id, value, created_by, icon_class, score)
             VALUES (%(fact_type_id)s, %(value)s, %(username)s, %(icon_class)s,
                     %(score)s)
          RETURNING id""")


class RecordRequestHandler(_RequestHandlerMixin, base.AdminCRUDRequestHandler):

    NAME = 'project-fact-type-enum'

    DELETE_SQL = 'DELETE FROM v1.project_fact_type_enums WHERE id=%(id)s'

    PATCH_SQL = re.sub(r'\s+', ' ', """\
        UPDATE v1.project_fact_type_enums
           SET fact_type_id=%(fact_type_id)s,
               last_modified_at=CURRENT_TIMESTAMP,
               last_modified_by=%(username)s,
               value=%(value)s,
               icon_class=%(icon_class)s,
               score=%(score)s
         WHERE id=%(id)s""")

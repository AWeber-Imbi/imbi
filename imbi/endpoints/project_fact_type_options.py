import re

from imbi.endpoints import base


class AdminCRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-project-fact-type-options'
    ID_KEY = ['id']
    FIELDS = ['id', 'fact_type_id', 'value', 'score']

    DELETE_SQL = re.sub(r'\s+', ' ', """\
    DELETE FROM v1.project_fact_type_options WHERE id=%(id)s""")

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT id, fact_type_id, created_at, created_by,
           last_modified_at, last_modified_by, value, score
      FROM v1.project_fact_type_options
     WHERE id=%(id)s""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
    UPDATE v1.project_fact_type_options
       SET fact_type_id=%(fact_type_id)s,
           last_modified_at=CURRENT_TIMESTAMP,
           last_modified_by=%(username)s,
           value=%(value)s,
           score=%(score)s
     WHERE id=%(id)s""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.project_fact_type_options
                (fact_type_id, value, created_by, score)
         VALUES (%(fact_type_id)s, %(value)s, %(username)s, %(score)s)
      RETURNING id;""")

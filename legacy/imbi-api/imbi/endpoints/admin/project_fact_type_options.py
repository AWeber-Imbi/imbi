import re

from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-project-fact-type-options'
    ID_KEY = ['project_type', 'fact_type', 'value']
    FIELDS = ['project_type', 'fact_type', 'value', 'score']

    DELETE_SQL = re.sub(r'\s+', ' ', """\
    DELETE FROM v1.project_fact_type_options
     WHERE project_type=%(project_type)s
       AND fact_type=%(fact_type)s
       AND value=%(value)s""")

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT project_type, fact_type, value, created_at, created_by, 
           last_modified_at, last_modified_by, score
      FROM v1.project_fact_type_options
     WHERE project_type=%(project_type)s
       AND fact_type=%(fact_type)s
       AND value=%(value)s""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
    UPDATE v1.project_fact_type_options
       SET project_type=%(project_type)s,
           fact_type=%(fact_type)s,
           value=%(value)s,
           last_modified_at=CURRENT_TIMESTAMP,
           last_modified_by=%(username)s,
           score=%(score)s
     WHERE project_type=%(current_project_type)s
       AND fact_type=%(current_fact_type)s
       AND value=%(current_value)s""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.project_fact_type_options
                (project_type, fact_type, value, created_by, score)
         VALUES (%(project_type)s, %(fact_type)s, %(value)s, %(username)s, 
                 %(score)s)
      RETURNING project_type, fact_type, value;""")

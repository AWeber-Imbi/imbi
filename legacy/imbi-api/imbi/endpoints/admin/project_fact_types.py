import re

from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-project-fact-types'
    ID_KEY = ['project_type', 'fact_type']
    FIELDS = ['project_type', 'fact_type', 'weight']

    DELETE_SQL = re.sub(r'\s+', ' ', """\
    DELETE FROM v1.project_fact_types
     WHERE project_type=%(project_type)s
       AND fact_type=%(fact_type)s;""")

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT project_type, fact_type, created_at, created_by, last_modified_at, 
           last_modified_by, weight
      FROM v1.project_fact_types
     WHERE project_type=%(project_type)s
       AND fact_type=%(fact_type)s;""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
    UPDATE v1.project_fact_types
       SET project_type=%(project_type)s,
           fact_type=%(fact_type)s,
           last_modified_at=CURRENT_TIMESTAMP,
           last_modified_by=%(username)s,
           weight=%(weight)s
     WHERE project_type=%(current_project_type)s
       AND fact_type=%(current_fact_type)s;""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.project_fact_types 
                (project_type, fact_type, created_by, weight)
         VALUES (%(project_type)s, %(fact_type)s, %(username)s, %(weight)s)
      RETURNING project_type, fact_type;""")

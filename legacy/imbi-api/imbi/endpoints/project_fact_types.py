import re

from imbi.endpoints import base


class AdminCRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-project-fact-types'
    ID_KEY = ['id']
    FIELDS = ['id', 'project_type_id', 'fact_type', 'weight']

    DELETE_SQL = re.sub(r'\s+', ' ', """\
    DELETE FROM v1.project_fact_types WHERE id=%(id)s;""")

    GET_SQL = re.sub(r'\s+', ' ', """\
    SELECT id, project_type_id, fact_type, created_at, created_by,
           last_modified_at, last_modified_by, weight
      FROM v1.project_fact_types
     WHERE id=%(id)s;""")

    PATCH_SQL = re.sub(r'\s+', ' ', """\
    UPDATE v1.project_fact_types
       SET project_type_id=%(project_type_id)s,
           fact_type=%(fact_type)s,
           last_modified_at=CURRENT_TIMESTAMP,
           last_modified_by=%(username)s,
           weight=%(weight)s
     WHERE id=%(id)s;""")

    POST_SQL = re.sub(r'\s+', ' ', """\
    INSERT INTO v1.project_fact_types
                (project_type_id, fact_type, created_by, weight)
         VALUES (%(project_type_id)s, %(fact_type)s, %(username)s, %(weight)s)
      RETURNING id;""")

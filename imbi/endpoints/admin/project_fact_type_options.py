from imbi.endpoints.admin import base


class CRUDRequestHandler(base.CRUDRequestHandler):

    NAME = 'admin-project-fact-type-options'
    ID_KEY = ['fact_type_id', 'option_id']
    ITEM_SCHEMA = 'admin/project_fact_type_option.yaml'
    FIELDS = ['fact_type_id', 'option_id', 'value', 'score']

    DELETE_SQL = """\
    DELETE FROM v1.project_fact_type_options
     WHERE fact_type_id=%(fact_type_id)s
       AND option_id=%(option_id)s"""

    GET_SQL = """\
    SELECT fact_type_id, option_id, created_at, modified_at, value, score
      FROM v1.project_fact_type_options
     WHERE fact_type_id=%(fact_type_id)s
       AND option_id=%(option_id)s;"""

    PATCH_SQL = """\
    UPDATE v1.project_fact_type_options
       SET fact_type_id=%(fact_type_id)s,
           option_id=%(option_id)s,
           modified_at=CURRENT_TIMESTAMP,
           value=%(value)s,
           score=%(score)s
     WHERE fact_type_id=%(fact_type_id)s
       AND option_id=%(option_id)s;"""

    POST_SQL = """\
    INSERT INTO v1.project_fact_type_options
                (fact_type_id, option_id, value, score)
         VALUES (%(fact_type_id)s, %(option_id)s, %(value)s, %(score)s)
      RETURNING fact_type_id, option_id;"""

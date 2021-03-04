import re

from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):

    NAME = 'project-fact-types'
    ID = 'project_id'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        SELECT c.id, c.name, c.fact_type, c.data_type, c.description,
               c.ui_options, c.weight,
               CASE WHEN c.fact_type = 'enum' THEN ARRAY(
                         SELECT value
                           FROM v1.project_fact_type_enums
                          WHERE fact_type_id = c.id
                       ORDER BY value ASC)
                    ELSE NULL END AS enum_values,
               CASE WHEN c.fact_type = 'range' THEN (
                         SELECT min(min_value)
                           FROM v1.project_fact_type_ranges
                          WHERE fact_type_id = c.id)
                  ELSE NULL END AS min_value,
               CASE WHEN c.fact_type = 'range' THEN (
                         SELECT max(max_value)
                           FROM v1.project_fact_type_ranges
                          WHERE fact_type_id = c.id)
                  ELSE NULL END AS max_value
          FROM v1.projects AS a
          JOIN v1.project_types AS b
            ON b.id = a.project_type_id
          JOIN v1.project_fact_types AS c
            ON b.id = ANY (c.project_type_ids)
         WHERE a.id = %(project_id)s
      ORDER BY c.name""")

import re

from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):

    NAME = 'project-activity-feed'
    ID = 'project_id'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        WITH created AS (
                SELECT created_at AS "when",
                       created_by AS who,
                       'created' AS what,
                       NULL AS fact_name,
                       NULL AS value
                  FROM v1.projects
                 WHERE id = %(project_id)s),
             updated AS (
                SELECT last_modified_at AS "when",
                       last_modified_by AS who,
                       'updated' AS what,
                       NULL AS fact_name,
                       NULL AS value
                  FROM v1.projects
                 WHERE id = %(project_id)s),
             facts AS (
                SELECT a.recorded_at AS "when",
                       a.recorded_by AS who,
                       'updated fact' AS what,
                       b.name AS fact_name,
                       a.value
                  FROM v1.project_facts AS a
                  JOIN v1.project_fact_types AS b
                    ON b.id = a.fact_type_id
                 WHERE a.project_id = %(project_id)s),
            combined AS (
                SELECT *
                  FROM created
                 UNION
                SELECT *
                  FROM updated
                 UNION
                SELECT *
                  FROM facts)
        SELECT a.when,
               a.who,
               b.display_name,
               a.what,
               a.fact_name,
               a.value
          FROM combined AS a
          JOIN v1.users AS b
            ON b.username = a.who
         ORDER BY a.when DESC;""")

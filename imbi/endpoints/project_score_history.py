import re

from imbi.endpoints import base


class CollectionRequestHandler(base.CollectionRequestHandler):

    NAME = 'project-score-history'
    ID = 'project_id'
    COLLECTION_SQL = re.sub(r'\s+', ' ', """\
        WITH history AS (
                SELECT changed_at::DATE AS "date",
                       max(score::INT) AS score
                  FROM v1.project_score_history
                 WHERE project_id = %(project_id)s
              GROUP BY changed_at::DATE),
             current AS (
                SELECT CURRENT_DATE AS "date",
                       v1.project_score(%(project_id)s)::INT AS score),
             records AS (
                SELECT "date", score
                  FROM history
                 UNION
                 SELECT CURRENT_DATE AS "date",
                        v1.project_score(%(project_id)s)::INT AS score)
            SELECT "date", max(score) AS score
              FROM records
          GROUP BY "date"
          ORDER BY "date" ASC;""")

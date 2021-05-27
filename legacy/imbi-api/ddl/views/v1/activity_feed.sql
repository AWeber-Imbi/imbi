CREATE OR REPLACE VIEW v1.activity_feed AS
  WITH created AS (
          SELECT a.created_at AS when,
                 a.created_by AS who,
                 'created' AS what,
                 a.id AS project_id,
                 a.name AS project_name,
                 b.name AS namespace,
                 b.id AS namespace_id,
                 c.name AS project_type
            FROM v1.projects AS a
            JOIN v1.namespaces AS b
              ON b.id = a.namespace_id
            JOIN v1.project_types AS c
              ON c.id = a.project_type_id
           WHERE a.last_modified_at IS NULL
             AND a.archived IS NOT TRUE
           ORDER BY a.created_at DESC
           LIMIT 1000),
       updated AS (
          SELECT a.last_modified_at AS when,
                 a.last_modified_by AS who,
                 'updated' AS what,
                 a.id AS project_id,
                 a.name AS project_name,
                 b.name AS namespace,
                 b.id AS namespace_id,
                 c.name AS project_type
            FROM v1.projects AS a
            JOIN v1.namespaces AS b
              ON b.id = a.namespace_id
            JOIN v1.project_types AS c
              ON c.id = a.project_type_id
           WHERE a.last_modified_at IS NOT NULL
             AND a.archived IS NOT TRUE
           ORDER BY a.last_modified_at DESC
           LIMIT 1000),
       updated_fact AS (
          SELECT a.recorded_at AS when,
                 a.recorded_by AS who,
                 'updated facts' AS what,
                 b.id AS project_id,
                 b.name AS project_name,
                 c.name AS namespace,
                 b.id AS namespace_id,
                 d.name AS project_type
            FROM v1.project_facts AS a
            JOIN v1.projects AS b
              ON b.id = a.project_id
            JOIN v1.namespaces AS c
              ON c.id = b.namespace_id
            JOIN v1.project_types AS d
              ON d.id = b.project_type_id
           WHERE b.archived IS NOT TRUE
           ORDER BY a.recorded_at DESC
           LIMIT 1000),
      combined AS (
          SELECT *
            FROM created
           UNION
          SELECT *
            FROM updated
           UNION
          SELECT *
            FROM updated_fact
      )
  SELECT a.who,
         b.display_name,
         b.email_address,
         a.what,
         a.project_id,
         a.project_name,
         a.namespace,
         a.namespace_id,
         a.project_type,
         max("when") as when
    FROM combined AS a
    JOIN v1.users AS b
      ON b.username = a.who
   GROUP BY a.who, b.username, b.email_address,
            a.what, a.project_id, a.project_name,
            a.namespace, a.namespace_id, a.project_type
   ORDER BY max(a.when) DESC LIMIT 1000;

GRANT SELECT ON v1.activity_feed TO reader;

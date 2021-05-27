SET search_path = v1;

CREATE OR REPLACE FUNCTION update_namespace_kpi_history() RETURNS void
       LANGUAGE sql
       SECURITY DEFINER AS $$
  WITH projects_with_facts AS (
          SELECT a.id, a.namespace_id
            FROM v1.projects AS a
       LEFT JOIN v1.project_fact_types AS b
              ON a.project_type_id = ANY(b.project_type_ids)
           WHERE a.archived IS NOT TRUE
        GROUP BY a.id, a.namespace_id
          HAVING count(b.*) > 0),
      project_scores AS (
          SELECT a.namespace_id,
                 v1.project_score(a.id)
            FROM projects_with_facts AS a
            JOIN v1.namespaces AS b
              ON b.id = a.namespace_id),
      project_counts AS (
          SELECT namespace_id, count(*)
            FROM v1.projects
           WHERE archived IS NOT TRUE
        GROUP BY namespace_id),
      namespace_stats AS (
         SELECT a.namespace_id,
                CURRENT_DATE AS scored_on,
                count(b.count) AS project_count,
                avg(a.project_score)::NUMERIC(9,2) AS health_score,
                count(a.*) * 100 AS total_possible_score,
                sum(a.project_score)::INT AS total_project_score
           FROM project_scores AS a
           JOIN project_counts AS b
             ON b.namespace_id = a.namespace_id
       GROUP BY a.namespace_id)
  INSERT INTO v1.namespace_kpi_history (namespace_id, scored_on, project_count, health_score, total_possible_score, total_project_score)
       SELECT *
         FROM namespace_stats;
$$;

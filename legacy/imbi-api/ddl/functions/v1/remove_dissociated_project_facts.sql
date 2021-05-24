SET search_path=v1, pg_catalog;

CREATE FUNCTION remove_dissociated_project_facts() RETURNS void AS $$
  WITH project_facts AS (
    SELECT b.id AS project_id,
           b.project_type_id,
           d.id AS fact_type_id
      FROM v1.project_facts AS a
      JOIN v1.projects AS b
        ON b.id = a.project_id
      JOIN v1.project_types AS c
        ON c.id = b.project_type_id
      JOIN v1.project_fact_types AS d
        ON d.id = a.fact_type_id),
       facts_to_delete AS (
    SELECT b.project_id, b.fact_type_id
      FROM v1.project_fact_types AS a
      JOIN project_facts AS b
        ON b.fact_type_id = a.id
     WHERE NOT (b.project_type_id = ANY (a.project_type_ids)))
    DELETE FROM v1.project_facts
     WHERE (project_id, fact_type_id) IN (
         SELECT project_id, fact_type_id
           FROM facts_to_delete)
$$ LANGUAGE sql SECURITY DEFINER;

COMMENT ON FUNCTION remove_dissociated_project_facts() IS 'Deletes project facts that are dissociated facts due to project fact type changes';

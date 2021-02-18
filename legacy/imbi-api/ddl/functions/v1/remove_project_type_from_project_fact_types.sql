SET search_path = v1;

CREATE OR REPLACE FUNCTION remove_project_type_from_project_fact_types() RETURNS trigger
       LANGUAGE plpgsql
       SECURITY DEFINER AS $$
  DECLARE
    project_fact_type  v1.project_fact_types%ROWTYPE;
  BEGIN
    FOR project_fact_type IN SELECT *
                               FROM v1.project_fact_types
                              WHERE project_type_ids @> ARRAY[OLD.id]
    LOOP
      UPDATE v1.project_fact_types
         SET project_type_ids = array_remove(project_fact_type.project_type_ids, OLD.id)
       WHERE id = project_fact_type.id;
    END LOOP;
    RETURN OLD;
  END;
$$;

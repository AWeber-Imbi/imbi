SET search_path = v1;

CREATE FUNCTION enforce_project_type_ids() RETURNS trigger
       LANGUAGE plpgsql
       SECURITY DEFINER AS $$
  DECLARE
    project_type        v1.project_types%ROWTYPE;
    project_type_id     INTEGER;
  BEGIN
    IF NEW.project_type_ids IS NOT NULL THEN
      FOREACH project_type_id IN ARRAY NEW.project_type_ids
      LOOP
        SELECT * INTO project_type
          FROM v1.project_types
         WHERE id = project_type_id;
        IF NOT FOUND THEN
          RAISE EXCEPTION 'project_type_id % not found in v1.project_types', project_type_id;
        END IF;
      END LOOP;
    END IF;
    RETURN NEW;
  END;
$$;

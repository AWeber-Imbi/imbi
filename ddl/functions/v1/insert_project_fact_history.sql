SET search_path = v1;

CREATE FUNCTION insert_project_fact_history() RETURNS trigger
       LANGUAGE plpgsql
       SECURITY DEFINER AS $$
  DECLARE
      fact_score  INTEGER;
      fact_weight INTEGER;
      recorded_by TEXT;
      recorded_at TIMESTAMP WITH TIME ZONE;
  BEGIN
    SELECT score INTO STRICT fact_score
      FROM v1.project_fact_type_options
     WHERE fact_type_id = NEW.fact_type_id
       AND value = NEW.value;

    SELECT weight INTO STRICT fact_weight
      FROM v1.project_fact_types
     WHERE id = NEW.fact_type_id;

    IF (TG_OP = 'INSERT') THEN
      recorded_at := NEW.created_at;
      recorded_by := NEW.created_by;
    ELSIF (TG_OP = 'UPDATE') THEN
      recorded_at := NEW.last_modified_at;
      recorded_by := NEW.last_modified_by;
    END IF;
    INSERT INTO project_fact_history(project_id, fact_type_id, recorded_at, recorded_by, value, score, weight)
         VALUES (NEW.project_id, NEW.fact_type_id, recorded_at, recorded_by, NEW.value, fact_score, fact_weight);
    RETURN NEW;
  END;
$$

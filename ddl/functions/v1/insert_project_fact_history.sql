SET search_path = v1;

CREATE FUNCTION insert_project_fact_history() RETURNS trigger
       LANGUAGE plpgsql
       SECURITY DEFINER AS $$
  DECLARE
    fact_type        v1.project_fact_types%ROWTYPE;
    recorded_by      TEXT;
    recorded_at      TIMESTAMP WITH TIME ZONE;
    fact_score       INTEGER := 0;
  BEGIN
    SELECT * INTO STRICT fact_type
      FROM v1.project_fact_types
     WHERE id = NEW.fact_type_id;

    IF (fact_type.fact_type = 'enum') THEN
      SELECT score INTO STRICT fact_score
        FROM v1.project_fact_type_enums
       WHERE fact_type_id = NEW.fact_type_id
         AND value = NEW.value;
    ELSIF (fact_type.fact_type = 'range') THEN
      SELECT score INTO STRICT fact_score
        FROM v1.project_fact_type_ranges
       WHERE fact_type_id = NEW.fact_type_id
         AND NEW.value::NUMERIC(9,2) BETWEEN min_value AND max_value;
    END IF;

    IF (TG_OP = 'INSERT') THEN
      recorded_at := NEW.created_at;
      recorded_by := NEW.created_by;
    ELSIF (TG_OP = 'UPDATE') THEN
      recorded_at := NEW.last_modified_at;
      recorded_by := NEW.last_modified_by;
    END IF;

    INSERT INTO v1.project_fact_history(project_id, fact_type_id, recorded_at, recorded_by, value, score, weight)
         VALUES (NEW.project_id, NEW.fact_type_id, recorded_at, recorded_by, NEW.value, fact_score, fact_type.weight);

    RETURN NEW;
  END;
$$;

SET search_path = v1;

CREATE FUNCTION insert_project_fact_history() RETURNS trigger
       LANGUAGE plpgsql
       SECURITY DEFINER AS $$
  DECLARE
    fact_type          v1.project_fact_types%ROWTYPE;
    fact_score         INTEGER := 0;
    last_project_score NUMERIC(9,2);
    new_project_score  NUMERIC(9,2);
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

    INSERT INTO v1.project_fact_history(project_id, fact_type_id, recorded_at, recorded_by, value, score, weight)
         VALUES (NEW.project_id, NEW.fact_type_id, NEW.recorded_at, NEW.recorded_by, NEW.value, fact_score, fact_type.weight);

    -- Insert the Project Score History if it's changed
      SELECT score INTO last_project_score
        FROM v1.project_score_history
       WHERE project_id = NEW.project_id
    ORDER BY changed_at DESC
       LIMIT 1;

      SELECT v1.project_score(NEW.project_id) INTO new_project_score;

      IF last_project_score IS NULL OR last_project_score != new_project_score THEN
        INSERT INTO v1.project_score_history (project_id, changed_at, score)
             VALUES (NEW.project_id, CURRENT_TIMESTAMP, new_project_score)
        ON CONFLICT (project_id, changed_at) DO UPDATE SET score = new_project_score;
      END IF;

    RETURN NEW;
  END;
$$;

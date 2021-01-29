SET search_path = v1;

CREATE OR REPLACE FUNCTION insert_project_fact_history() RETURNS trigger
      LANGUAGE plpgsql
      AS $$
  DECLARE
      fact_recorded_by TEXT;
      fact_project_type TEXT;
      fact_score INTEGER;
      fact_weight NUMERIC(5,2);
  BEGIN

    SELECT project_type
      INTO fact_project_type
      FROM projects
     WHERE "name" = NEW."name"
      AND namespace = NEW.namespace;

    SELECT weight
      INTO fact_weight
      FROM project_fact_types
     WHERE fact_type = NEW.fact_type
       AND project_type = fact_project_type;

    SELECT score
      INTO fact_score
      FROM project_fact_type_options
     WHERE fact_type = NEW.fact_type
       AND project_type = fact_project_type;

    IF (TG_OP = 'INSERT') THEN
        SELECT NEW.created_by
          INTO fact_recorded_by;
    ELSIF (TG_OP = 'UPDATE') THEN
        SELECT CASE NEW.last_modified_by
               WHEN NULL THEN NEW.created_by
               ELSE NEW.last_modified_by
                END
          INTO fact_recorded_by;
    END IF;

    INSERT INTO project_fact_history(namespace, "name", fact_type, recorded_by, value, score, weight)
    VALUES (NEW.namespace, NEW."name", NEW.fact_type, fact_recorded_by, NEW.value, fact_score, fact_weight);


    RETURN NEW;

  END;
  $$

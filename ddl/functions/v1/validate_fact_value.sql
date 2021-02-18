SET search_path = v1;

CREATE FUNCTION validate_fact_value() RETURNS trigger
       LANGUAGE plpgsql
       SECURITY DEFINER AS $$
  DECLARE
    fact_type        v1.project_fact_types%ROWTYPE;
    fact_type_enum   v1.project_fact_type_enums%ROWTYPE;
    fact_type_range  v1.project_fact_type_ranges%ROWTYPE;
  BEGIN
    SELECT * INTO STRICT fact_type
      FROM v1.project_fact_types
     WHERE id = NEW.fact_type_id;

    IF (fact_type.fact_type = 'enum') THEN
      SELECT * INTO fact_type_enum
        FROM v1.project_fact_type_enums
       WHERE fact_type_id = NEW.fact_type_id
         AND value = NEW.value;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'value not found in v1.project_fact_type_enums';
      END IF;
    ELSIF (fact_type.fact_type = 'range') THEN
      SELECT * INTO fact_type_range
        FROM v1.project_fact_type_ranges
       WHERE fact_type_id = NEW.fact_type_id
         AND NEW.value::NUMERIC(9,2) BETWEEN min_value AND max_value;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'value not found in v1.project_fact_type_ranges';
      END IF;
    END IF;
    RETURN NEW;
  END;
$$;

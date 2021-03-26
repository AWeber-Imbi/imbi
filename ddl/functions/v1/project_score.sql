SET search_path=v1, pg_catalog;

CREATE OR REPLACE FUNCTION project_score(IN in_project_id INTEGER) RETURNS NUMERIC(9,2)
       LANGUAGE plpgsql
       SECURITY DEFINER AS $$
  DECLARE
    project_type_id  INTEGER;
    fact_record      RECORD;
    fact_weight      NUMERIC(9,5);
    score            NUMERIC(9,2) := 0;
    total_weight     NUMERIC(9,5);
    weighted_score   NUMERIC(9,5);
  BEGIN
    SELECT projects.project_type_id INTO STRICT project_type_id
      FROM v1.projects
     WHERE id = in_project_id;

    SELECT sum(weight)::NUMERIC(9,2) INTO total_weight
      FROM v1.project_fact_types
     WHERE project_type_id = ANY(project_type_ids);

    IF total_weight IS NULL THEN
      RETURN 100.00;
    END IF;

    FOR fact_record IN SELECT CASE WHEN b.value IS NULL THEN 0
                                   ELSE CASE WHEN a.fact_type = 'enum' THEN (
                                                   SELECT project_fact_type_enums.score::NUMERIC(9,2)
                                                     FROM v1.project_fact_type_enums
                                                    WHERE fact_type_id = b.fact_type_id
                                                      AND value = b.value)
                                             WHEN a.fact_type = 'range' THEN (
                                                   SELECT project_fact_type_ranges.score::NUMERIC(9,2)
                                                     FROM v1.project_fact_type_ranges
                                                    WHERE fact_type_id = b.fact_type_id
                                                      AND b.value::NUMERIC(9,2) BETWEEN min_value AND max_value)
                                             WHEN a.data_type = 'boolean' AND b.value = 'true' THEN 100
                                             ELSE 0
                                         END
                               END AS score,
                              a.name,
                              b.value,
                              a.weight
                         FROM v1.project_fact_types AS a
                    LEFT JOIN v1.project_facts AS b
                           ON b.fact_type_id = a.id
                          AND b.project_id = in_project_id
                        WHERE project_type_id = ANY(a.project_type_ids)
    LOOP
      fact_weight := fact_record.weight / total_weight;
      weighted_score := fact_record.score * fact_weight;
      score := score + weighted_score;
    END LOOP;
  RETURN score;
END
$$;

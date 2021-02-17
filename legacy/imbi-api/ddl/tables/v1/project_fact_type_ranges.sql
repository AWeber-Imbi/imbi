SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_fact_type_ranges (
  id                 SERIAL                    NOT NULL  PRIMARY KEY,
  created_at         TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by         TEXT                      NOT NULL,
  last_modified_at   TIMESTAMP WITH TIME ZONE,
  last_modified_by   TEXT,
  fact_type_id       INTEGER                   NOT NULL,
  min_value          NUMERIC(9,2)              NOT NULL,
  max_value          NUMERIC(9,2)              NOT NULL,
  score              INTEGER                   CONSTRAINT valid_score CHECK (score IS NOT NULL AND score BETWEEN 0 AND 100)  DEFAULT 0,
  FOREIGN KEY (fact_type_id) REFERENCES project_fact_types (id) ON UPDATE CASCADE ON DELETE RESTRICT
);

COMMENT ON TABLE project_fact_type_ranges IS 'Defines the values that are used in a column for project health score';
COMMENT ON COLUMN project_fact_type_ranges.id IS 'The surrogate ID for the fact type option';
COMMENT ON COLUMN project_fact_type_ranges.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_fact_type_ranges.created_by IS 'The user created the record';
COMMENT ON COLUMN project_fact_type_ranges.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_fact_type_ranges.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN project_fact_type_ranges.fact_type_id IS 'The fact type the option is for';
COMMENT ON COLUMN project_fact_type_ranges.min_value IS 'The min value of the fact for the score';
COMMENT ON COLUMN project_fact_type_ranges.max_value IS 'The max value of the fact for the score';
COMMENT ON COLUMN project_fact_type_ranges.score IS 'The score for this value, with a maximum value of 100';

GRANT SELECT ON project_fact_type_ranges TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_fact_type_ranges TO admin;

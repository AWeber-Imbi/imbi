SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_fact_type_options (
  fact_type_id  UUID                      NOT NULL,
  option_id     UUID                      NOT NULL,
  created_at    TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  modified_at   TIMESTAMP WITH TIME ZONE,
  value         TEXT                      NOT NULL,
  score         INTEGER                   CONSTRAINT valid_score CHECK (score IS NOT NULL AND score BETWEEN 0 AND 100)  DEFAULT 0,
  PRIMARY KEY (fact_type_id, option_id),
  FOREIGN KEY (fact_type_id) REFERENCES project_fact_types (id) ON UPDATE CASCADE ON DELETE RESTRICT
);

COMMENT ON TABLE project_fact_type_options IS 'Defines the values that are used in a column for project health score';
COMMENT ON COLUMN project_fact_type_options.fact_type_id IS 'The fact type ID';
COMMENT ON COLUMN project_fact_type_options.option_id IS 'The fact type option ID';
COMMENT ON COLUMN project_fact_type_options.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_fact_type_options.modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_fact_type_options.value IS 'The fact column value';
COMMENT ON COLUMN project_fact_type_options.score IS 'The score for this value, with a maximum value of 100';

GRANT SELECT ON project_fact_type_options TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_fact_type_options TO admin;

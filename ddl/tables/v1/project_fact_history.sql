SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_fact_history (
  namespace     TEXT                      NOT NULL,
  "name"        TEXT                      NOT NULL,
  fact_type     TEXT                      NOT NULL,
  recorded_at   TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  recorded_by   TEXT                      NOT NULL,
  value         TEXT                      NOT NULL,
  score         INTEGER                   NOT NULL,
  weight        NUMERIC (5,2)             NOT NULL,
  PRIMARY KEY (namespace, "name", recorded_at),
  FOREIGN KEY (namespace, "name") REFERENCES projects (namespace, "name") ON UPDATE CASCADE ON DELETE CASCADE
);

COMMENT ON TABLE project_fact_history IS 'Stores the historical record of fact values for a project, including the score and weight of the score';
COMMENT ON COLUMN project_fact_history.namespace IS 'The namespace of the project that the fact is for';
COMMENT ON COLUMN project_fact_history.name IS 'The project name the fact is for';
COMMENT ON COLUMN project_fact_history.fact_type IS 'The project fact type';
COMMENT ON COLUMN project_fact_history.recorded_at IS 'When the record was created at';
COMMENT ON COLUMN project_fact_history.recorded_by IS 'The user who created the new project fact record';
COMMENT ON COLUMN project_fact_history.value IS 'The fact value';
COMMENT ON COLUMN project_fact_history.score IS 'The score for this value, with a maximum value of 100';
COMMENT ON COLUMN project_fact_history.weight IS 'The weight from 0.0 to 100.0 of the total score for a project. Total weight should across all columns for a project type should not exceed 100.';

GRANT SELECT ON project_fact_history TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_fact_history TO admin;

SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_fact_history (
  project_id    INTEGER                   NOT NULL,
  fact_type_id  INTEGER                   NOT NULL,
  recorded_at   TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  recorded_by   TEXT                      NOT NULL,
  value         TEXT,
  score         INTEGER                   NOT NULL,
  weight        INTEGER                   NOT NULL,
  PRIMARY KEY (project_id, fact_type_id, recorded_at),
  FOREIGN KEY (project_id) REFERENCES projects (id) ON UPDATE CASCADE ON DELETE CASCADE,
  FOREIGN KEY (fact_type_id) REFERENCES project_fact_types (id) ON UPDATE CASCADE ON DELETE CASCADE
);

COMMENT ON TABLE project_fact_history IS 'Stores the historical record of fact values for a project, including the score and weight of the score';
COMMENT ON COLUMN project_fact_history.project_id IS 'The project the record is for';
COMMENT ON COLUMN project_fact_history.fact_type_id IS 'The fact type for the record';
COMMENT ON COLUMN project_fact_history.recorded_at IS 'When the record was created at';
COMMENT ON COLUMN project_fact_history.recorded_by IS 'The user who created the new project fact record';
COMMENT ON COLUMN project_fact_history.value IS 'The fact value';
COMMENT ON COLUMN project_fact_history.score IS 'The score for this value, with a maximum value of 100';
COMMENT ON COLUMN project_fact_history.weight IS 'The weight from 0.0 to 100.0 of the total score for a project. Total weight should across all columns for a project type should not exceed 100.';

GRANT SELECT ON project_fact_history TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_fact_history TO writer;

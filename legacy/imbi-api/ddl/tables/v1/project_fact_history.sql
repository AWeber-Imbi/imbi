SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_fact_history (
  project_id    UUID                      NOT NULL,
  fact          TEXT                      NOT NULL,
  recorded_at   TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  value         TEXT                      NOT NULL,
  score         INTEGER                   NOT NULL,
  weight        NUMERIC (5,2)             NOT NULL,
  PRIMARY KEY (project_id, fact, recorded_at),
  FOREIGN KEY (project_id) REFERENCES projects (id) ON UPDATE CASCADE ON DELETE CASCADE
);

COMMENT ON TABLE project_fact_history IS 'Stores the historical record of fact values for a project, including the score and weight of the score';
COMMENT ON COLUMN project_fact_history.project_id IS 'The project ID';
COMMENT ON COLUMN project_fact_history.fact IS 'The fact name';
COMMENT ON COLUMN project_fact_history.recorded_at IS 'When the record was created at';
COMMENT ON COLUMN project_fact_history.value IS 'The fact value';
COMMENT ON COLUMN project_fact_history.score IS 'The score for this value, with a maximum value of 100';
COMMENT ON COLUMN project_fact_history.weight IS 'The weight from 0.0 to 100.0 of the total score for a project. Total weight should across all columns for a project type should not exceed 100.';

GRANT SELECT ON project_fact_history TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_fact_history TO admin;

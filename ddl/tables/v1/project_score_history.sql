SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_score_history (
  project_id  INTEGER                   NOT NULL,
  changed_at  TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  score       NUMERIC(9,2)              NOT NULL,
  PRIMARY KEY (project_id, changed_at),
  FOREIGN KEY (project_id) REFERENCES projects (id) ON UPDATE CASCADE ON DELETE CASCADE
);

COMMENT ON TABLE project_score_history IS 'Table detailing project scores as facts change';
COMMENT ON COLUMN project_score_history.project_id IS 'The project ID';
COMMENT ON COLUMN project_score_history.changed_at IS 'When the record was created / score changed at';
COMMENT ON COLUMN project_score_history.score IS 'The score value';

GRANT SELECT ON project_score_history TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_score_history TO admin;

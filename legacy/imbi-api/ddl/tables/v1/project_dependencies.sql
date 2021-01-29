SET search_path=v1, public, pg_catalog;

CREATE TABLE IF NOT EXISTS project_dependencies (
  project_id            INTEGER                   NOT NULL,
  dependency_id         INTEGER                   NOT NULL,
  created_at            TIMESTAMP WITH TIME ZONE  NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by            TEXT                      NOT NULL,
  PRIMARY KEY (project_id, dependency_id),
  FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE ON UPDATE CASCADE,
  FOREIGN KEY (dependency_id) REFERENCES projects (id) ON DELETE CASCADE ON UPDATE CASCADE
);

COMMENT ON TABLE project_dependencies IS 'Relationships between a project and the projects that it depends upon';
COMMENT ON COLUMN project_dependencies.project_id IS 'The project that is dependent';
COMMENT ON COLUMN project_dependencies.dependency_id IS 'The project that is the dependency';
COMMENT ON COLUMN project_dependencies.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_dependencies.created_by IS 'The user that created the record';

GRANT SELECT ON project_dependencies TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_dependencies TO writer;

SET search_path=v1, public, pg_catalog;

CREATE TABLE IF NOT EXISTS project_dependencies (
  namespace             TEXT                      NOT NULL,
  "name"                TEXT                      NOT NULL,
  dependency_namespace  TEXT                      NOT NULL,
  dependency_name       TEXT                      NOT NULL,
  created_at            TIMESTAMP WITH TIME ZONE  NOT NULL DEFAULT CURRENT_TIMESTAMP,
  created_by            TEXT                      NOT NULL,
  PRIMARY KEY (namespace, "name", dependency_namespace, dependency_name),
  FOREIGN KEY (namespace, "name") REFERENCES projects (namespace, "name") ON DELETE CASCADE ON UPDATE CASCADE,
  FOREIGN KEY (dependency_namespace, dependency_name) REFERENCES projects (namespace, "name") ON DELETE CASCADE ON UPDATE CASCADE
);

COMMENT ON TABLE project_dependencies IS 'Relationships between a project and the projects that it depends upon';
COMMENT ON COLUMN project_dependencies.namespace IS 'The project namespace';
COMMENT ON COLUMN project_dependencies.name IS 'The project name';
COMMENT ON COLUMN project_dependencies.dependency_namespace IS 'The namespace of the project the project depends on';
COMMENT ON COLUMN project_dependencies.dependency_name IS 'The name of the project the project depends on';
COMMENT ON COLUMN project_dependencies.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_dependencies.created_by IS 'The user that created the record';

GRANT SELECT ON project_dependencies TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_dependencies TO writer;

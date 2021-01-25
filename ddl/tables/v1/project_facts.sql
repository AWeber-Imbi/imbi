SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_facts (
  namespace         TEXT                      NOT NULL,
  "name"            TEXT                      NOT NULL,
  fact_type         TEXT                      NOT NULL,
  created_at        TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by        TEXT                      NOT NULL,
  last_modified_at  TIMESTAMP WITH TIME ZONE,
  last_modified_by  TEXT,
  value             TEXT                      NOT NULL,
  PRIMARY KEY (namespace, "name", fact_type),
  FOREIGN KEY (namespace, "name") REFERENCES projects (namespace, "name") ON UPDATE CASCADE ON DELETE CASCADE
);

COMMENT ON TABLE project_facts IS 'Stores the current facts for a project';
COMMENT ON COLUMN project_facts.namespace IS 'The project namespace';
COMMENT ON COLUMN project_facts.name IS 'The project name';
COMMENT ON COLUMN project_facts.fact_type IS 'The project fact type';
COMMENT ON COLUMN project_facts.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_facts.created_by IS 'The user created the record';
COMMENT ON COLUMN project_facts.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_facts.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN project_facts.value IS 'The fact value';

GRANT SELECT ON project_facts TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_facts TO admin;

SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_fact_types (
  id           UUID                      NOT NULL  PRIMARY KEY,
  created_at   TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  modified_at  TIMESTAMP WITH TIME ZONE,
  project_type TEXT                      NOT NULL,
  "name"       TEXT                      NOT NULL,
  weight       INTEGER                   CONSTRAINT valid_weight CHECK (weight IS NOT NULL AND weight BETWEEN 0 AND 100)  DEFAULT 0,
  FOREIGN KEY (project_type) REFERENCES project_types ("name") ON UPDATE CASCADE ON DELETE RESTRICT,
  UNIQUE      (project_type, "name")
);

COMMENT ON TABLE project_fact_types IS 'Defines the types that are used for project health score';
COMMENT ON COLUMN project_fact_types.id IS 'The fact type ID';
COMMENT ON COLUMN project_fact_types.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_fact_types.modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_fact_types.project_type IS 'The project type';
COMMENT ON COLUMN project_fact_types.name IS 'The fact type name';
COMMENT ON COLUMN project_fact_types.weight IS 'The weight from 0 to 100 of the total score for a project. Total weight should across all types for a project type should not exceed 100.';

GRANT SELECT ON project_fact_types TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_fact_types TO admin;

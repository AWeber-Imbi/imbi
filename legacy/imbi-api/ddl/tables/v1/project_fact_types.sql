SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_fact_types (
  project_type       TEXT                      NOT NULL,
  fact_type          TEXT                      NOT NULL,
  created_at         TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by         TEXT                      NOT NULL,
  last_modified_at   TIMESTAMP WITH TIME ZONE,
  last_modified_by   TEXT,
  weight             INTEGER                   CONSTRAINT valid_weight CHECK (weight IS NOT NULL AND weight BETWEEN 0 AND 100)  DEFAULT 0,
  PRIMARY KEY (project_type, fact_type),
  FOREIGN KEY (project_type) REFERENCES project_types ("name") ON UPDATE CASCADE ON DELETE RESTRICT
);

COMMENT ON TABLE project_fact_types IS 'Defines the types that are used for project health score';
COMMENT ON COLUMN project_fact_types.project_type IS 'The project type';
COMMENT ON COLUMN project_fact_types.fact_type IS 'The fact type name';
COMMENT ON COLUMN project_fact_types.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_fact_types.created_by IS 'The user created the record';
COMMENT ON COLUMN project_fact_types.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_fact_types.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN project_fact_types.weight IS 'The weight from 0 to 100 of the total score for a project. Total weight should across all types for a project type should not exceed 100.';

GRANT SELECT ON project_fact_types TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_fact_types TO admin;

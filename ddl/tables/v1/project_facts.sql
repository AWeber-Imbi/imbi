SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_facts (
  project_id    UUID                      NOT NULL,
  fact_type_id  UUID                      NOT NULL,
  created_at    TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  modified_at   TIMESTAMP WITH TIME ZONE,
  value         TEXT                      NOT NULL,
  PRIMARY KEY (project_id, fact_type_id),
  FOREIGN KEY (project_id) REFERENCES projects (id) ON UPDATE CASCADE ON DELETE CASCADE,
  FOREIGN KEY (fact_type_id) REFERENCES project_fact_types (id) ON UPDATE CASCADE ON DELETE RESTRICT
);

COMMENT ON TABLE project_facts IS 'Stores the current facts for a project';
COMMENT ON COLUMN project_facts.project_id IS 'The project ID';
COMMENT ON COLUMN project_facts.fact_type_id IS 'The fact type ID';
COMMENT ON COLUMN project_facts.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_facts.modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_facts.value IS 'The fact value';

GRANT SELECT ON project_facts TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_facts TO admin;

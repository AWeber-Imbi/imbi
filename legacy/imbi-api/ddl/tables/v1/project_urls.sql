SET search_path=v1;

CREATE TABLE IF NOT EXISTS project_urls (
  project_id        INTEGER                   NOT NULL,
  environment       TEXT                      NOT NULL,
  created_at        TIMESTAMP WITH TIME ZONE  NOT NULL  DEFAULT CURRENT_TIMESTAMP,
  created_by        TEXT                      NOT NULL,
  last_modified_at  TIMESTAMP WITH TIME ZONE,
  last_modified_by  TEXT,
  url               TEXT,
  PRIMARY KEY (project_id, environment),
  FOREIGN KEY (project_id) REFERENCES projects (id) ON UPDATE CASCADE ON DELETE CASCADE,
  FOREIGN KEY (environment) REFERENCES environments ("name") ON UPDATE CASCADE ON DELETE CASCADE
);

COMMENT ON TABLE project_urls IS 'Stores the current urls for a project';
COMMENT ON COLUMN project_urls.project_id IS 'The project ID';
COMMENT ON COLUMN project_urls.environment IS 'The URL to to the service in the environment';
COMMENT ON COLUMN project_urls.created_at IS 'When the record was created at';
COMMENT ON COLUMN project_urls.created_by IS 'The user created the record';
COMMENT ON COLUMN project_urls.last_modified_at IS 'When the record was last modified';
COMMENT ON COLUMN project_urls.last_modified_by IS 'The user that last modified the record';
COMMENT ON COLUMN project_urls.url IS 'The URL value';

GRANT SELECT ON project_urls TO reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON project_urls TO writer;
